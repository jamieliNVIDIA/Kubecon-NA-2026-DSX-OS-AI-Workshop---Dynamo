# Request continuity and migration: technical notes

Researched November 4, 2026 for workshop section 3.1. The primary implementation
below is the workshop lock's Dynamo source revision
`ea23e5130c1bfbadec477b99449d0cee5598caa0`. A comparison with upstream
`b8ac9836e1460c7c4a35782860179ef574deaf83` appears at the end. These are source
and documentation findings; this research did not inject faults into the live
cluster or execute the upstream tests.

## The mechanism to teach

For a supported text-generation request, the frontend retains its tokenized
prompt and accumulates generated token IDs from successful response chunks.
If a backend attempt fails with an eligible error, it dispatches another attempt
whose input is the original prompt plus that generated prefix. The replacement
engine processes that input and generates the continuation. The frontend keeps
the original client response stream open while switching backend attempts.

The migration path does not retrieve the failed worker's KV tensors. A cold
replacement worker can recompute state from the retained token sequence; a
compatible cached prefix can reduce that cost. This connects directly to the
fundamentals distinction between context and its recomputable working state.

Code: [`track_response`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/migration.rs#L708)
appends IDs and rebases the token budget;
[`new_stream`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/migration.rs#L494)
dispatches a clone of that updated request. The
[vLLM prompt construction](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/components/src/dynamo/vllm/handlers.py#L3270)
uses the preprocessed request rather than constructing a new user conversation.

```mermaid
sequenceDiagram
    participant C as Client
    participant F as Frontend and migrator
    participant A as Worker A
    participant B as Worker B
    C->>F: One streaming request, prompt P
    F->>A: P, output budget 10
    A-->>F: Generated IDs o1, o2, o3
    F-->>C: Stream the corresponding output
    A--xF: Backend attempt fails
    Note over F: Retain P + o1,o2,o3; classify error; check retry budget
    F->>B: P + o1,o2,o3, remaining output budget 7
    Note over B: Reuse available cache or rebuild working state
    B-->>F: Continue with o4 and subsequent tokens
    F-->>C: Continue the original response stream
```

The numeric example assumes ordinary single-choice output and no earlier stop.
The prefix is input to B, so B does not have to emit those three output tokens
again. It is continuing the same generated sequence, rather than asking the
model to produce the original answer again and attempting to splice two answers.
The code also subtracts accepted output lengths from `min_tokens` when set.

## Where the state lives

| State | Owner and role during recovery |
| --- | --- |
| Client HTTP/SSE response | Remains hosted by the frontend; the client does not issue the internal retry. |
| Original prompt plus observed output IDs | Frontend-local replay state used to construct the next attempt. |
| Remaining output budget, request options, routing/trace context | Retained with the preprocessed request; some values are updated per attempt. |
| Withheld hidden-stop-prefix text | The pinned implementation checkpoints this frontend decoder state into `jail_seed` for the next decoder. |
| Worker GPU KV/recurrent state | Not copied by this replay mechanism. Missing state must be rebuilt or supplied through a separate cache mechanism. |
| Worker CUDA context, graphs, engine process | Not restored by request migration; engine recovery is the next workshop topic. |
| Sampler/constraint/application state | Token replay is not a general checkpoint of all these states; the limitations below matter. |

The state is local to the frontend handling this request. The
[`MigrationState` fields](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/protocols/common/preprocessor.rs#L125)
include failed-worker exclusions and a request lifecycle;
[`PreprocessedRequest`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/protocols/common/preprocessor.rs#L294)
marks that state as frontend-only and skips it during serialization. This is
not durable request replication across frontend replicas.

The replay boundary is what the frontend has received and accepted from the
backend. It is not an acknowledgement of which bytes the application has read.
Tokens computed on A but never received at the frontend need not be reproduced
identically. Keep the frontend and client connection alive in the demonstration.

## Position in the processing pipeline

The normal tokenized pipeline is assembled in
[`PreprocessedRouting::build_pipeline`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/entrypoint/input/common.rs#L470):

```text
HTTP/API processing -> preprocessing -> Migration -> backend token processing
                    -> encoder/prefill routing when present -> worker dispatch

worker output -> backend token processing -> Migration -> API response processing
              -> the original HTTP response stream
```

`Migration` wraps the downstream engine with a per-request `RetryManager`.
Each new attempt invokes that downstream pipeline again. The outer API request
remains in place. An alternative preprocessed-input pipeline uses the same
migration operator around raw engine outputs.

One detail prevents an overly simple "all frontend state just stays alive"
explanation: backend token decoding is inside the retried portion and a fresh
decoder can be created per attempt. The pinned code carries withheld stop-prefix
text into that decoder through `jail_seed`. See the
[decoder setup](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/backend.rs#L177)
and the
[real-backend regression cases](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/migration.rs#L3244).
Do not generalize this into a guarantee that every parser and sampler state is
preserved for every request type.

## Detecting a failure and selecting another worker

There are two entry points: a dispatch/setup failure before output starts, and
an error on an existing backend response stream. Both use bounded retries;
only the latter needs the generated prefix.

The runtime can expose a connection failure, an engine-shutdown/incomplete-stream
error, or discovery-driven cancellation of a removed worker's registered
streams. Its internal response protocol records whether generation completed.
If transport ends without that completion marker, the
[`addressed_router` decoder](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/runtime/src/pipeline/network/egress/addressed_router.rs#L246)
produces a typed disconnect instead of treating EOF as successful generation.
[Worker removal](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/runtime/src/pipeline/network/egress/addressed_router.rs#L1141)
can cancel registrations even when there is no clean producer error.

[`is_migratable_for_request`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/migration.rs#L80)
uses semantic error reasons and routing constraints, not a blanket retry of
every HTTP or engine error. Examples include disconnect, connection/response
timeout, engine shutdown, incomplete stream, and worker unavailability.
Worker-specific overload can be eligible too; cancellation, request deadlines,
pool-wide exhaustion, and classifier rejection are terminal in this policy.

The ordinary runtime router
[temporarily inhibits a failed worker](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/runtime/src/pipeline/network/egress/push_router.rs#L1927)
while discovery converges. The
[client's default inhibition window](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/runtime/src/component/client.rs#L24)
is five seconds, configurable through `DYN_RUNTIME_INHIBITED_DURATION_SECS`.
KV routing additionally keeps
[request-local failed-worker exclusions](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/kv_router/routing_host/kv_selection.rs#L189).
These are separate from waiting for Kubernetes to replace the failed Pod.

For a live-but-stalled producer, the request-plane inactivity timer is optional:
`DYN_HTTP_BACKEND_STREAM_TIMEOUT_SECS` is disabled when unset or zero in this
revision. The runtime uses it to produce a retryable timeout and inhibit the
worker. The HTTP monitor uses twice that configured duration as an outer safety
net; an outer timeout can end the client stream rather than migrate it. Avoid
promising a universal failure-detection time.

## Streaming outcome and the recovery pause

In
[`RetryManager::next`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/migration.rs#L421),
an eligible failure that successfully establishes another attempt is consumed
internally. The loop resumes reading backend chunks, which flow through the
original frontend response. If migration is disabled, disallowed, exhausted,
or fails to establish a replacement, the terminal error is propagated.

After HTTP response headers have been sent, failure is conveyed within the
stream. The pinned
[SSE monitor](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/http/service/disconnect.rs#L595)
can send an error JSON frame followed by `[DONE]`. That external terminator is
different from the runtime's internal generation-completion marker. HTTP 200
and `[DONE]` alone do not prove that generation completed successfully.

The remaining pause can include detection, rerouting/queueing, prefill of the
accumulated context, and delivery of the next generated chunk. Treat this as a
causal explanation rather than a measured sum: implementations can overlap
work. A surviving, already loaded engine avoids model startup but may have a
cold prefix cache and higher load. Migration restores request progress before
Shadow/Snapshot necessarily restores fleet capacity.

The docs' "uninterrupted" language should be taught as supported continuation
within the same client request. It does not establish unchanged token cadence,
preservation of all GPU work, identical future stochastic samples, or an SLO.

### Live follow-up: SSE worker attribution

The subsequent [presenter-demo investigation](workshop-request-continuity-demo.md)
confirmed continuation through an EngineCore SIGKILL and exposed a telemetry
boundary: `nvext.worker_id` keeps the original worker ID after migration in
this pinned runtime. `RequestTracker` records those fields in `OnceLock`;
[`record_once_u64`](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/protocols/common/timing.rs)
logs a conflicting write when the retry selects another worker and preserves
the first value.

Use the initial SSE ID to identify the fault target. To prove the handoff,
correlate the response ID in the failed route attempt with its HTTP request
span, the `migration retry scheduled` event, preserved output-token count and
the new decode-worker selection. In the first live capture that count was 31,
and the selected peer was already Ready before the fault. The same client
response ID continued through a successful `stop` and DONE. The SSE field
alone cannot provide the exact last-old/first-peer client gap in this runtime.

## Configuration and support boundaries

Configure the frontend, not each GPU worker. The
[pinned deployment guide](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/docs/fern/pages/kubernetes/fault-tolerance/request-migration.md)
defines:

| Setting or condition | Meaning for the workshop |
| --- | --- |
| `DYN_MIGRATION_LIMIT=0` / `--migration-limit 0` | Default: no replacement attempts. The operator still owns the initial attempt. |
| `DYN_MIGRATION_LIMIT=3` | Up to three replacement attempts in addition to the original dispatch; bounded recovery, not an indefinite wait for capacity. |
| `DYN_MIGRATION_MAX_SEQ_LEN` / `--migration-max-seq-len` | Optional prompt-plus-generated-token cap. Exceeding it disables subsequent migration/tracking for that request; it does not truncate the prompt or reject the original generation. Exactly at the cap remains eligible. |
| `n > 1` | The pinned constructor disables migration because it does not track independent continuation state for each choice. |
| Guided decoding / constrained structured output | Disabled: a fresh constraint FSM is not advanced by treating the partial output as prompt context. |
| Explicit worker-instance pin | Rerouting is disallowed for that pinned phase. Observe the serving worker ID instead of hard-pinning the failure-demo request. Session affinity is a different mechanism. |
| Frontend loss, client disconnect, or exhausted/deadlined request | Outside the worker-continuation demonstration; no durable client reconnection/recovery protocol is provided here. |

Do not copy the guide's illustrative 32k sequence cap into the long-context
AgentX demonstration. Choose any cap from the actual supported prompt plus
output lengths, or leave it unset for the qualified demonstration.

The constructor's cap check occurs after the initial `new_stream` call, so the
cap is not a general pre-dispatch input validator. Source comments also leave
embedding-prompt replay, generated-token penalty state, and thinking-token
budgets as unresolved work. A supported text example does not qualify every
multimodal or sampling configuration.

For coding agents, ordinary tool-call generation and constrained JSON decoding
are not interchangeable categories. Inspect the actual request options before
claiming support. Migration of model generation also does not replay an agent
program or guarantee exactly-once execution of external tool side effects.

## Planned termination

Keep `SIGTERM`/draining separate from an abrupt process kill. On planned
termination, workers remove endpoints from discovery and allow admitted work
to drain. If a request is interrupted later, frontend migration can recover it
when eligible and when a healthy destination exists. Kubernetes' termination
grace period must allow the intended internal drain/cleanup windows. See the
[pinned graceful-shutdown guide](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/docs/fern/pages/kubernetes/fault-tolerance/graceful-shutdown.md).

## Evidence to show in the demonstration

Use the same representative coding request in both arms, with client retries
disabled. Keep the frontend alive, choose single-choice supported output, and
avoid an explicit worker pin. Observe the serving worker and kill that engine
only after visible output. Capture:

- One client request and its timestamped output/error/terminal frames.
- The fault time, old and new worker identities, backend attempts, and resumed
  output, using route traces and migration logs to correlate them.
- Actual client completion and the inter-chunk gap across the fault.
- The surviving capacity and load; recovery of the failed worker is a separate
  event on the same timeline.

Metrics include `dynamo_frontend_model_migration_total`,
`dynamo_frontend_model_migration_duration_seconds`, and
`dynamo_frontend_model_migration_max_seq_len_exceeded_total`.
Their interpretation needs care: the code records duration success when
`next_generate.generate` returns a replacement stream, before the outer loop
has consumed its continuation. An eligible failure can also enter migration
counter/error handling after retries are exhausted. A counter increment is not
proof of a successful dispatch, resumed client tokens, or final completion.

The source includes regression cases for initial and mid-stream retries,
budget rebasing, cancellation, sequence caps, explicit pins, and withheld
stop-prefix text. The
[mid-stream unit case](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/lib/llm/src/migration.rs#L1751)
checks five output tokens before failure and five after, in sequence. Upstream
also has
[aggregated vLLM fault tests](https://github.com/ai-dynamo/dynamo/blob/ea23e5130c1bfbadec477b99449d0cee5598caa0/tests/fault_tolerance/migration/test_vllm.py#L380).
Those inspected tests are useful fixtures, not a claim that this workshop's
Super VL runtime has passed a newly executed fault test.

## Version differences that affect claims

The inspected
[upstream migration implementation](https://github.com/ai-dynamo/dynamo/blob/b8ac9836e1460c7c4a35782860179ef574deaf83/lib/llm/src/migration.rs)
retains the same token-prefix replay model but adds details absent from the
locked implementation's migration module:

| Area | Locked revision | Inspected upstream revision |
| --- | --- | --- |
| Frontend decoder checkpoint | Carries withheld stop-prefix text. | Carries a fuller decoder checkpoint, including buffered IDs and stop-filter state. |
| Usage accounting | No migration-level `rebase_usage` function. | Explicitly reclassifies replayed completion tokens that the replacement engine counted as input; do not assume identical usage semantics across builds. |
| Generation artifacts | No matching constructor exclusion. | Explicitly disables migration for generation-artifact capture requests. |
| Replay-buffer lifecycle | Stops appending once retries are unavailable. | Additionally releases the retained prompt when no further attempt can be dispatched. |

The guided-output and multi-choice exclusions and the sampler/embedding TODOs
are still present in the inspected upstream source. Recheck these boundaries
when the final workshop runtime changes. Prefer "continue a supported token
generation after worker failure" over a blanket promise of complete engine or
application-state preservation.
