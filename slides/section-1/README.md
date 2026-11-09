# Section 1 slide mockups

Twelve editable slides for the 20-minute inference-fundamentals section, based
on [the working outline](../../WORKSHOP_OUTLINE.md). This draft covers section 1
only and does not change that outline.

## Live presentation

- Title: **Dynamo KubeCon — Section 1: Inference Fundamentals (Mockup)**
- Spaces Page ID: `page_9a77d39d12ac81919286575a4b07c7c8`
- Initial connected artifact reference:
  `artifact_external_dd6d09de-b9a1-4056-8a29-bb6dd7f851eb`
- Connection used for the comment revisions:
  `artifact_external_7f253a73-8b8c-4761-96dc-53e6d205b724`

Continue editing the existing live deck. If the connection expires, connect the
same Page ID again and use its returned artifact reference.

## Slides

| Slide | Topic | Minutes |
| --- | --- | ---: |
| 1 | The Coding Agent Loop | 1.5 |
| 2 | Each Turn Sends More Context | 1.5 |
| 3 | Inside a vLLM Server | 2 |
| 4 | Prefill and Generation | 2 |
| 5 | Reuse the KV Cache of a Shared Prefix | 1.5 |
| 6 | Cached State Changes the Cost of a Request | 1.5 |
| 7 | A Dynamo-Managed Service | 2 |
| 8 | Describe the Service With a DGD | 2 |
| 9 | Startup Time Breakdown | 2 |
| 10 | Replay the Coding-Agent Workload | 1 |
| 11 | Latency From the Agent's Perspective | 1.5 |
| 12 | System Throughput and User Interactivity | 1.5 |
| **Total** | | **20** |

The first six slides establish the agent and vLLM concepts before Dynamo is
introduced. Prefix reuse is visual only. The cache-recomputation caveat is
explicit. Diagrams and text are native editable slide objects; no timing or
performance numbers are fabricated.

Each slide includes presenter notes with its purpose, timing cue, sources, and
any remaining demonstration preparation.

## Authoring sources

- `build.mjs`: the initial authoring callback for Artifact Session. It uses the
  session's prebound presentation, rather than producing a second local deck.
- `assets/`: original logo and corporate icons extracted from the bundled NVIDIA
  presentation skill's official template and icon archives.
- `slide_review.md`: visual review findings and repair status.

The draft uses NVIDIA Sans, NVIDIA brand colors, and original corporate artwork.
It follows the light content-slide style with flat editable diagrams.

For a new blank copy, import `buildSection1` into Artifact Session and call it
with successive `input.indexes` batches, starting with `[1]`. Authoring calls
should use a 120-second timeout; a default 30-second call timed out when saving
three slides. Do not rerun the initial builder over slides that already exist.
Make subsequent edits through the existing presentation and stable element IDs.

`reviseCommentedSlides` rebuilds only the bodies of slides 5, 9, and 12, retaining
their slide IDs and attached comment threads. It also simplifies the existing
cache label on slide 4 to KV cache, preserving the other live edits on that slide.
The live presentation is the source of truth for manual edits; the initial
builder is not intended to overwrite them.

## Comment revisions

- Slide 5 reuses slide 2's Code, User task, Tool call, and Tool result blocks. It
  shows KV cache within an explicit vLLM server boundary and distinguishes cache
  reuse from sending the same input text again.
- Slide 9 is an editable waterfall layout. Dashed TBD bars have no measured
  offsets or durations, and no numeric time scale is shown.
- Slide 12 contrasts system output throughput normalized by allocated GPU count
  (tok/s/GPU) with per-request generation speed (tok/s/user). AIPerf's per-user
  generation-rate metric excludes TTFT; TTFT and complete-request latency remain
  separate measurements.

The original three comment threads remain attached to the same slides for review.

## Remaining demo preparation

- Choose the final minimal Super VL DGD. Slide 8 is clearly labeled as an excerpt,
  with runtime and pod-template settings omitted.
- Capture the actual startup phase starts and durations. Slide 9 is a waterfall
  mockup, not a proportional or measured timing chart.
- Select the trace and runnable AIPerf command, then add actual baseline results.
- Confirm the precise metric aggregation definitions and selected percentiles.

The original planning deck, sections 2 and 3, and live cluster resources are not
edited by this mockup.
