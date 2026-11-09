# Section 1 visual review

All 12 live slide renders were inspected individually at 1280 × 720, together
with a deck overview. Initial geometry inspection found no off-canvas elements.

## Round 1

| Slide | Finding | Severity | Status |
| --- | --- | --- | --- |
| 1 | Two-line session caption needs more assigned text-frame height. | Low | DONE: expanded the frame. |
| 4 | State-to-generation arrow crosses its explanatory label. | Medium | DONE: routed the arrow to the right of the label. |
| 4 | Explicitly map generation to the term decode used later. | Medium | DONE: labeled the phase Generation (decode). |
| 7 | Namespace background obscures the incoming HTTP arrowhead. | Medium | DONE: corrected stacking and arrow endpoint. |
| 8 | YAML text extends outside the background and approaches its excerpt caption. | High | DONE: removed redundant comment lines and used a top-aligned monospace font. |
| 11 | TTFT explanation wraps to three lines in a frame intended for two. | Low | DONE: shortened the explanation and increased the frame height. |

Slides 2, 3, 5, 6, 9, 10, and 12 had no observed clipping, unintended overlap,
off-canvas content, or illegible labels. Speaker notes identify diagrams as
schematic, the DGD as an incomplete excerpt, and numerical demo data as pending.

## Round 2

Re-rendered and inspected slides 1, 4, 7, 8, and 11 individually. All Round 1
findings are resolved. The other seven slides were unchanged from their reviewed
renders. The deck has 12 slides and 277 native editable shapes, and every slide
has presenter notes. Timing cues total 20 minutes.

No issues found. All slides pass visual review for this mockup. The pending
manifest, measurements, workload selection, and live-demo preparation remain
explicit in the notes and README.

## Round 3 — user comment revisions

Re-rendered and inspected slides 4, 5, 9, and 12 after applying the three comments.

| Slide | Comment or consistency change | Review result |
| --- | --- | --- |
| 4 | Use the established KV cache term. | The label is simplified; the user's live Read/Update diagram edits remain intact. |
| 5 | Clarify what is reused and where it lives. | Matches slide 2's request blocks, labels the server boundary, and shows server-side KV cache reuse separately from new-context processing. |
| 9 | Replace the phase sequence with a waterfall design. | Dashed TBD bars, a pending-timing label, and a visible layout-only note make the absence of measured timing explicit. |
| 12 | Distinguish system throughput from user throughput. | Large tok/s/GPU and tok/s/user labels, separate denominators, and a TTFT caveat make the distinction explicit. |

The 12-slide deck and the three original comment-thread targets are preserved.
No clipping or unintended overlap was observed in the changed renders. The
waterfall remains pending actual measurements. No new visual issues found.
