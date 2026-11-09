# Hybrid cache block metadata and router qualification

The native-context worker logs six cache-group sizes of 4224 tokens and an LCM
of 4224, despite the starting CLI `--block-size 64` and frontend
`--kv-cache-block-size 64`. That log alone does not establish a routing mismatch.

The **public upstream code at the pinned Dynamo runtime revision**
`ea23e5130c1bfbadec477b99449d0cee5598caa0` explains the managed path:

1. [Worker initialization](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/components/src/dynamo/vllm/worker_factory.py#L1415)
   calls `configure_kv_event_block_size` after engine initialization and before
   setting up KV publication.
2. [Cache metadata selection](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/components/src/dynamo/vllm/cache_info.py#L44)
   queries engine cache-group metadata and selects the main-attention block
   size, retaining it as `dynamo_kv_event_block_size`.
3. [Publication and registration](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/components/src/dynamo/vllm/main.py#L491)
   use that configured event block size for both the publisher and the model
   deployment card (`main.py`, lines 518 and 955).
4. [Managed model discovery](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/discovery/watcher.rs#L588)
   constructs the KV chooser with `card.kv_cache_block_size`. It does not use the
   frontend CLI value in place of that managed card's advertised size.

Thus source supports dynamic agreement between publication and routing. This is
source-based reasoning, not direct observation of a later KV-routing run. Before
accepting the policy comparison, retain discovery/event ingress, actual matching
or routing evidence, and server cache counters. Do not silently change the
locked block-size flags to force the logged LCM to equal the starting CLI value.

All links above are public Apache-2.0 upstream files. Automatic approval review
rejected an attempted full source-file export from the runtime Pod as potentially
proprietary and beyond benchmark authorization. That command did not execute.
The alternative analysis used public GitHub files, existing startup logs, and
benchmark artifacts; no Pod source was exported.
