"""Nemotron TP2 adapter for upstream Snapshot's CuInterpose workload contract."""
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
import traceback
from collections.abc import Mapping

os.environ['VLLM_WORKER_MULTIPROC_METHOD'] = 'spawn'

CONTROL = Path(os.environ.get('SNAPSHOT_CONTROL_DIR', '/snapshot-control'))


def phase(name, **values):
    report = {'phase': name, 'utc': dt.datetime.now(dt.timezone.utc).isoformat(), **values}
    print('SNAPSHOT_PHASE ' + json.dumps(report), flush=True)
    CONTROL.joinpath('test-phase.json').write_text(json.dumps(report))


async def main():
    from transformers import AutoTokenizer
    from vllm import SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.v1.engine.async_llm import AsyncLLM
    from fastapi import FastAPI
    import uvicorn

    args = json.loads(sys.argv[1])
    phase('initializing', model=args['model'], revision=args['revision'], tp=args['tensor_parallel_size'],
          multiprocessing=os.environ['VLLM_WORKER_MULTIPROC_METHOD'])
    engine = AsyncLLM.from_engine_args(AsyncEngineArgs(**args, enable_sleep_mode=True))
    tokenizer = AutoTokenizer.from_pretrained(args['model'], revision=args['revision'],
                                             trust_remote_code=True, local_files_only=True)

    async def generate(prompt, label):
        tokens = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}],
            tokenize=True, add_generation_prompt=True, enable_thinking=False)
        if isinstance(tokens, Mapping):
            tokens = tokens['input_ids']
        result = None
        async for output in engine.generate({'prompt_token_ids': tokens},
                SamplingParams(temperature=0, max_tokens=32), label):
            result = output
        if result is None or not result.outputs:
            raise RuntimeError('No generated result')
        return result.outputs[0].text.strip()

    before = await asyncio.wait_for(generate('Reply with exactly READY.', 'before-capture'), timeout=180)
    if before.strip('.') != 'READY':
        raise RuntimeError('Unexpected pre-capture response: ' + repr(before))
    phase('pause-generation', before=before)
    start = time.monotonic()
    await asyncio.wait_for(engine.pause_generation(), timeout=120)
    phase('release-kv-cache')
    await asyncio.wait_for(engine.release_kv_cache_memory(), timeout=180)
    # Shared mappings remain intact here. The Snapshot agent's CuInterpose
    # coordinator owns their preparation after all participants are quiesced.
    phase('prepared', before=before, preparation_seconds=time.monotonic() - start)
    CONTROL.joinpath('preparation-complete').write_text('prepared\n')
    while not CONTROL.joinpath('allow-capture').exists():
        await asyncio.sleep(0.5)
    phase('capture-ready')
    CONTROL.joinpath('ready-for-snapshot').write_text('ready\n')
    while not CONTROL.joinpath('restore-complete').exists():
        await asyncio.sleep(0.5)
    phase('restoring-wake')
    await asyncio.wait_for(engine.wake_up(), timeout=180)
    phase('restoring-resume')
    await asyncio.wait_for(engine.resume_generation(), timeout=120)
    await asyncio.wait_for(engine.check_health(), timeout=30)
    after = await asyncio.wait_for(generate('Reply with exactly READY.', 'after-restore'), timeout=180)
    if after.strip('.') != 'READY':
        raise RuntimeError('Unexpected restored response: ' + repr(after))
    phase('restored-inference', before=before, after=after)
    app = FastAPI()

    @app.get('/test')
    async def test():
        text = await asyncio.wait_for(generate('Reply with exactly READY.', 'http-' + str(time.time_ns())), timeout=180)
        return {'text': text, 'model': args['model'], 'revision': args['revision'], 'tp': 2}

    server = uvicorn.Server(uvicorn.Config(app, host='0.0.0.0', port=8000))
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            await task
            raise RuntimeError('API failed during startup')
        await asyncio.sleep(0.1)
    CONTROL.joinpath('vllm-restore-ready').write_text(after + '\n')
    phase('serving', after=after)
    await task


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception:
        text = traceback.format_exc()
        CONTROL.joinpath('test-error.txt').write_text(text)
        print(text, file=sys.stderr, flush=True)
        raise
