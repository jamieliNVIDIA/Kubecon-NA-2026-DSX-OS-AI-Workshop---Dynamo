#!/usr/bin/env python3
"""Build the NVIDIA Dynamo workshop deck: one self-contained HTML file from an authored section plus ai-dynamo.org decks.

Each source deck keeps its own markup, CSS (scoped to a wrapper) and interactive
scripts; the six per-deck navigation engines are replaced by one unified engine
(DW) that also renders a cover slide and a divider slide per section.
"""
import html as htmlmod
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / 'src'                      # the six decks downloaded from https://ai-dynamo.org/slides/
WORK = HERE / '.work'                   # scratch files (evaluated slide arrays, syntax checks)
OUT = HERE.parent / 'dynamo-workshop.html'
WORK.mkdir(parents=True, exist_ok=True)

DECKS = [   # source decks built into the page; every slide stays in the DOM, PROGRAM below decides what is shown
    dict(id='fund', file=None, family='N'),               # authored: build/fundamentals.py
    dict(id='scaling', file=None, family='N'),            # authored: build/scaling.py (scaling opener + disaggregation)
    dict(id='extras', file=None, family='N'),             # authored: build/extras.py (slides placed inside deck-based sections)
    dict(id='resiliency', file=None, family='N'),         # authored: build/resiliency.py (resiliency opener, demo cues, recap)
    dict(id='kvcrdemo', file=None, family='N'),           # authored: build/kvcrdemo.py (KVCR demo cue, try it)
    dict(id='aiperf', file='aiperf.html', family='A'),
    dict(id='router', file='router.html', family='B'),
    dict(id='kvcr', file='kvcr.html', family='A'),
    dict(id='intro', file='intro.html', family='A'),      # Introduction to Dynamo deck: only its KVCR overview slide is shown
    dict(id='ft', file='ft.html', family='B'),
    dict(id='mx', file='mx-snapshot.html', family='B'),
    dict(id='planner', file='planner-grove.html', family='P'),   # Planner × Grove deck: static slides, own builder
]
# setup.html (Deploy and tune Dynamo) is no longer built: that section was cut from the workshop on 2026-11-05.

# The workshop program: host sections in order. Each entry is (deck, slide indexes) in the deck's own 0-based order
# ('*' = every slide). The #numbers in the comments are slide numbers of the 134-slide deck before the 2026-11-05 trim.
PROGRAM = [
    dict(id='fund', name='Inference fundamentals + scaling', agenda=False,   # no slide list on this divider
         desc='Inference request processing, GPU memory allocation, prefix caching, single-worker deployment, performance metrics and scaling.',
         slides=[('fund', '*'),              # #3-#19 without 5, 7, 13, 15, 19; the demo (#17) moved ahead of the DGD (#14)
                 ('aiperf', [9]),            # #30 "Used by": the one AIPerf slide kept, closing the baseline part
                 ('extras', [4]),            # AIPerf demo cue, authored 2026-11-08: the demo runs on this slide
                 ('scaling', [0, 2])]),      # the scaling opener (outline 2.1) without its static curve slide; its divider was dropped on 2026-11-06
    dict(id='mx', name='ModelExpress',
         desc='A new replica takes too long to help: pull the weights from GPUs that already hold them, over NIXL, instead of reading storage again.',
         slides=[('scaling', [3]),           # "Add a replica, then wait": moved here from the scaling opener on 2026-11-07, it sets up the wait
                 ('mx', [2]),                # #121 the ModelExpress title; #120 and #123/#124 are cut
                 ('extras', [1]),            # demo cue: start replica 2, then back to the slides while it loads (authored 2026-11-07)
                 ('mx', [3]),                # #122 "Ask → pull from a peer, or seed from storage"
                 ('intro', [14]),            # intro deck "NIXL": the transfer library under MX, disaggregation and KVCR (added 2026-11-07)
                 ('extras', [2])]),          # matched startup results: storage, peer weights, plus compile caches (authored 2026-11-07)
    dict(id='router', name='Dynamo Router',
         desc='Why a second worker barely helped the slowest turns, then how the Dynamo router picks a worker: what workers report about their cache, how overlap and load become one cost, and the policy file that holds the knobs.',
         slides=[('extras', [3]),                     # measured opener (outline 2.3): one worker vs two, round-robin vs KV (authored 2026-11-08)
                 ('kvcr', [1]),                       # "Three requirements for KV cache management", moved here from KVCR on 2026-11-07
                 ('router', [6, 7, 2, 21])]),         # #58 (moved first), #59 (before #54 on 2026-11-07), #54, #73; the title slide #52 and the "Deep dive 1" hero #57 are cut
    dict(id='kvcr', name='KVCR (KV Cache Runner)',
         desc='A subagent lands on a worker that has never seen its context. KVCR copies that context from the worker that has it instead of recomputing it: how it works, a live demo, and early results on real workloads.',
         slides=[('intro', [11]),            # intro deck "KVCR \u00b7 KV Cache Runner": the one-slide overview, with each piece's maturity (moved first 2026-11-08)
                 ('kvcr', [11]),             # #95 "Copy", reframed as the subagent case (outline 2.4); #84 title and #86 "Approach" cut 2026-11-08
                 ('kvcrdemo', [0]),          # demo cue: the subagent lands on B (runbook stop 5, live; authored 2026-11-08)
                 ('kvcr', [8]),              # #92 results, after the demo: AgentX first, labeled as the KVCR team's
                 ('kvcrdemo', [1])]),        # try it: pip install kvcr, maturity, what the workshop ran
    dict(id='disagg', name='Disaggregation',
         desc='Prefill and decode worker pools, KV-cache transfers, performance tradeoffs and deployment configuration.',
         slides=[('scaling', [4, 5, 6, 7, 9])]),   # rebuilt 2026-11-07 for outline 2.5: why, what, flow, gains, Dynamo; the costs slide (8) was cut on 2026-11-08
    dict(id='auto', name='Autoscaling',
         desc='Planner scaling policies, latency targets and replica counts.',
         slides=[('scaling', [10]),                # authored Planner intro (2.6)
                 ('planner', [4]),                 # Planner × Grove deck #s5 "Targets and knobs"; #s11 "DGD to Grove mapping" was cut on 2026-11-08
                 ('extras', [5])]),                # the 10-minute break, authored 2026-11-08
    dict(id='adm', name='Admission control',
         desc='Request rejection, queueing policies and session-aware admission under load.',
         slides=[('router', [15, 31, 32, 34])]),  # #67 (moved after KVCR) + the session-aware slides (redone 2026-11-07); the "Deep dive 3" hero #66 and "The control loop" (33) were cut on 2026-11-08
    dict(id='ft', name='Resiliency',
         desc='Keep serving when something breaks: request migration and graceful shutdown keep requests alive, GPU Memory Service and Shadow Engine recover from software faults in seconds, and KVCR-Guard keeps the KV cache through an engine or GPU failure. Hardware faults come next, with Snapshot.',
         slides=[('ft', [0]),                # #102 the deck's cover
                 ('resiliency', [0, 1]),     # three questions on the aggregated topology (replaces #103, which is disaggregated); demo cue, migration off
                 ('ft', [4]),                # #106 request migration; case 2 of the demo runs from the terminal after it
                 ('ft', [9]),                # #111 graceful shutdown
                 ('resiliency', [3]),        # the request survived, the capacity did not: the startup bar again
                 ('ft', [10, 11]),           # #112 GPU Memory Service, #113 Shadow Engine
                 ('resiliency', [4]),        # demo cue: Shadow Engine failover, on a different model
                 ('kvcr', [6, 9])]),         # #90, #93: KVCR-Guard, after Shadow (a promoted engine starts with an empty cache)
                                             # cut on 2026-11-07: #107 cancellation, #110 router fault tolerance, #116 incident walkthrough
                                             # cut on 2026-11-08: resiliency 2, the migration-on results (its case 2 cues moved to #106's notes)
    dict(id='snap', name='Snapshot',                      # the section was "ModelExpress + Snapshot" until 2026-11-08; #128 keeps that name
         desc='Checkpoint a warmed-up worker once, including GPU state, and restore it on any node in seconds. Together with ModelExpress: restore the engine, then wake with weights from a peer.',
         slides=[('mx', [6, 7, 8]),               # #125, #126, #127 "what gets saved" (back on 2026-11-08); the deck's cover #119 is cut: its headline is on #128
                 ('resiliency', [5]),             # demo cue: delete the worker Pod, Snapshot restores it (same node, local NVMe)
                 ('extras', [0]),                 # SGLang cold start vs Snapshot benchmark (authored 2026-11-06), moved ahead of #128 on 2026-11-08
                 ('mx', [9, 10, 11]),             # #128, #129, #130: the ModelExpress + Snapshot subsection
                 ('mx', [13]),                    # #132 "Same traffic. Spike it, break it."
                 ('resiliency', [6])]),           # recap: which layer handles which failure, and what we showed; closes the deck
]


# ----------------------------------------------------------------------------- slide patches (by deck + original index)
def patch_kvcr_requirements(h):
    """#85: drop requirement 4 "Signal aware"; the slide becomes three requirements."""
    h2 = re.sub(r'\s*<div class="card rq-c"><span class="rq-n">4</span>.*?use that signal\.</p></div>', '', h, count=1, flags=re.S)
    if h2 == h or 'rq-n">4<' in h2:
        raise SystemExit('build: kvcr requirements: card 4 not removed')
    h = must(h2, 'grid-template-columns:repeat(4,1fr)', 'grid-template-columns:repeat(3,1fr)')
    h = must(h, 'Four requirements for KV cache management', 'Three requirements for KV cache management')
    h = must(h, 'Store and retrieve, avoid hot spots, assume failures, take input from the workload.',
             'Store and retrieve, avoid hot spots, assume failures.')
    h = re.sub(r'\s*<li>4\. Signal aware:.*?</li>', '', h, count=1, flags=re.S)
    return h


def mark_fix(h):
    """#110: visible FIX marker (the slide is flagged for rework)."""
    return re.sub(r'(<section\b[^>]*>)', r'\1<div class="dw-fixtag">FIX</div>', h, count=1)


def gates_heading(h):
    """#67: the four gate slides that followed were cut, so the strip no longer points at "the next four slides"."""
    return must(h, '<div class="gates-h">How, in the next four slides</div>', '<div class="gates-h">The four gates</div>')


def router_eyebrow(old, new):
    """Router slides name the source deck's four deep dives ("Deep dive 1 · Performance 1/4"). The workshop shows a few of those
    slides in sections of its own, so the deep-dive numbers and counts point at slides that are not there."""
    return lambda h: must(h, f'<div class="eyebrow" data-enter style="--i:0">{old}</div>',
                          f'<div class="eyebrow" data-enter style="--i:0">{new}</div>')


def admission_title(h):
    """#66, the Admission control title: "Deep dive 3 of 4" is the source deck's numbering. The new title also names the slide in
    the chrome and on the section divider."""
    h = must(h, 'data-title="Deep dive 3"', 'data-title="Admission control"')
    return router_eyebrow('Deep dive 3 of 4', 'Inside the Dynamo Router')(h)


def policy_file_acts(h):
    """#73 "One policy file": its text points back at the source deck's Acts 1-3."""
    h = router_eyebrow('Deep dive 4 · Customization <span class="step">1/4</span>', 'The router · customization')(h)
    h = must(h, 'The cost knobs from Act 1, the thresholds from Act 2, and the classes and classifier from Act 3 all live in one file.',
             'The cost knobs, the busy thresholds, and the classes and classifier all live in one file.')
    return must(h, '<td>the cost model from Act 1</td>', '<td>the default cost model</td>')


def mx_part_label(h):
    """ModelExpress opener (#121): it opens a section of its own now, so drop the "01" and the "Part 1" eyebrow."""
    h = must(h, '<div class="secnum" data-enter style="--i:0">01</div>\n      <div class="eyebrow" data-enter style="--i:1">Part 1</div>',
             '<div class="eyebrow" data-enter style="--i:1">NVIDIA Dynamo · faster worker startup</div>')
    return h


def snapshot_part_label(h):
    """Snapshot opener (#125): there is no Part 1 before it in the workshop, so drop the "02" and the "Part 2" eyebrow."""
    return must(h, '<div class="secnum" data-enter style="--i:0">02</div>\n      <div class="eyebrow snap" data-enter style="--i:1">Part 2</div>',
                '<div class="eyebrow snap" data-enter style="--i:1">NVIDIA Dynamo · faster recovery</div>')


def snapshot_saved_teaser(h):
    """#127 "what gets saved", before the Snapshot demo: its teaser for the weights-free checkpoint read "Part 3 · future plan".
    In the workshop that subsection follows the demo and the benchmark, and no slide calls it a future plan."""
    return must(h, '<span>Part 3 · future plan</span>', '<span>Later in this section</span>')


def together_part_label(h):
    """ModelExpress + Snapshot opener (#128): drop the "03" and the "Part 3" eyebrow. The heading breaks the line after
    "ModelExpress", so name the slide explicitly; the chrome read "ModelExpress+ Snapshot"."""
    h = must(h, '<div class="secnum" data-enter style="--i:0">03</div>\n      <div class="eyebrow" data-enter style="--i:1">Part 3</div>',
             '<div class="eyebrow" data-enter style="--i:1">NVIDIA Dynamo · the two together</div>')
    return set_section_attr(h, 'data-title', 'ModelExpress + Snapshot')


def mx_peer_discovery(h):
    """#122 "Ask → pull from a peer": show the loader flag as the demo terminal does (`mx` is only an alias), on two lines so
    it fits its box, and say that the workshop demo finds its source through a Kubernetes Service rather than an MX server."""
    h = must(h, '<text x="50" y="324" class="t-h">New worker</text><text x="50" y="366" class="t-d t-mono">--load-format mx</text>'
                '<text x="50" y="404" class="t-d">vLLM, starting up</text>',
             '<text x="50" y="318" class="t-h">New worker</text><text x="50" y="354" class="t-d t-mono">--load-format</text>'
             '<text x="50" y="384" class="t-d t-mono">modelexpress</text><text x="50" y="418" class="t-d">vLLM, starting up</text>')
    return must(h, '<text x="496" y="414" class="t-s">metadata only</text>',
                '<text x="496" y="404" class="t-s">metadata only</text><text x="496" y="434" class="t-s">our demo: a k8s Service</text>')


def mx_notes(js):
    """#122 notes, to match the slide patch above, plus the loader chain of the pinned MX 0.6.0 (the notes skipped
    InstantTensor). The notes live in the deck's SPEAKER_NOTES script, not in the markup."""
    js = must(js, 'a new vLLM worker starts with <code>--load-format mx</code> (plugin <code>modelexpress</code>) and asks the ModelExpress server.',
              'a new vLLM worker starts with <code>--load-format modelexpress</code> (<code>mx</code> is an alias) and asks the ModelExpress '
              'server. In our demo there is no MX server: the worker finds the source through the first replica\'s <code>mx-source</code> '
              'Kubernetes Service (<code>MX_METADATA_BACKEND=k8s-service</code>).')
    return must(js, 'MX tries paths in this order: P2P RDMA → ModelStreamer → GDS → default loader.',
                'MX tries paths in this order (pinned MX 0.6.0): P2P RDMA → InstantTensor → ModelStreamer → GDS → disk.')


def snapshot_saved_notes(js):
    """#127 notes: their "slide 2" is a source-deck slide the workshop cuts, and their transition led straight into ModelExpress +
    Snapshot, where the workshop has the live demo and the benchmark first."""
    js = must(js, "That's the same storage fan-out problem as slide 2, just moved.",
              "That's the same storage fan-out problem as in the ModelExpress section, just moved.")
    return must(js, '<strong>Transition:</strong> \\"What if we drop the weights from the checkpoint too, and let ModelExpress bring them back?\\"',
                '<strong>Transition:</strong> next, the live demo: delete the worker Pod and watch Snapshot restore its replacement from '
                'node-local NVMe. Keep the question for after the benchmark: what if we drop the weights from the checkpoint too, and let '
                'ModelExpress bring them back?')


def intro_nixl(h):
    """Intro deck "NIXL", shown after the ModelExpress mechanism: drop the "Deep-dive deck coming" chip and add notes that
    tie it to the demo's transfer path (the deck has no notes for it)."""
    h = must(h, '<span class="cp-go none">Deep-dive deck coming</span>', '')
    return must(h, '\n</section>',
                '<aside class="notes"><p>ModelExpress decides which GPU holds the weights; NIXL moves the bytes. The same library carries '
                'the KV cache from prefill to decode in disaggregation and between KVCR host pools, so this is the one place we introduce '
                'it.</p><p>In our demo NIXL runs its libfabric backend over EFA, eight rails per TP rank: 39.22 GB per GPU in 1.6 to '
                '6.2 s across the three live runs. The storage side of the slide is outside the demo, and the two 20&#215; cards are the '
                'partners&#8217; published KV-from-storage results, not workshop measurements.</p></aside>\n</section>')


def planner_inline_use(h):
    """Planner #s11: the second decode instance is a <use> clone of the first. Scoped CSS does not reach into a <use>
    shadow tree (the clone rendered as a black box), so replace it with a translated copy of the group."""
    m = re.search(r'<g id="inst1">', h)
    depth, end = 0, None
    for t in re.finditer(r'<g\b|</g>', h[m.end():]):
        if t.group(0) == '</g>':
            if depth == 0:
                end = m.end() + t.end()
                break
            depth -= 1
        else:
            depth += 1
    inner = h[m.end():end - len('</g>')]
    return must(h, '<use href="#inst1" x="366"/>', '<g transform="translate(366 0)">' + inner + '</g>')


def migration_no_seq_cap(h):
    """#106: our coding prompts average about 108K tokens, so the source's DYN_MIGRATION_MAX_SEQ_LEN=32000 would leave most of them
    non-migratable; the workshop demo sets no cap. Also say what migration needs from the frontend."""
    h = must(h, '\n<span class="k">DYN_MIGRATION_MAX_SEQ_LEN</span>=<span class="n">32000</span>',
             '\n<span class="c"># DYN_MIGRATION_MAX_SEQ_LEN unset: no cap</span>')
    return must(h, 'and <code>n&gt;1</code> requests return an error instead.</p>',
                'and <code>n&gt;1</code> requests return an error instead. <b>The frontend must survive:</b> the tokens it replays '
                'live in its memory.</p>')


def gms_standby_cost(h):
    """#112: the parked shadow engine is not free, and the outline asks to label the standby's resources."""
    return must(h, 'weights mapped. Waits on a lock.</span>', 'weights mapped. Waits on a lock. Costs 4&#8211;8 GiB more per GPU.</span>')


def guard_failover(h):
    """KVCR #90, shown in Resiliency: a title for the divider's agenda, its maturity, and the run on our cluster. The slide tells
    it the other way round (B's engine fails, A fetches), so the added line names no engine."""
    h = must(h, 'data-title="Failures"', 'data-title="KVCR-Guard failover"')
    h = must(h, '<span class="kicker">KVCR-Guard · try it</span>',
             '<span class="kicker">KVCR-Guard · try it <span class="badge">in development</span></span>')
    h = must(h, '\n  <aside class="notes"><ul>',   # top right, out of the column's flow, so the diagram keeps its size
             '\n  <div class="dim" style="position:absolute;top:clamp(28px,6.5vh,76px);right:max(16px,clamp(18px,5vw,88px));'
             'width:min(38vw,640px);font-size:clamp(12px,1.8vh,18px);line-height:1.4;background:var(--surface);border:1px solid '
             'var(--line);border-left:6px solid var(--green-fill);border-radius:12px;padding:10px 16px">'
             '<b style="color:var(--text)">On our cluster</b> (Super VL, requests pinned): with one engine down, its peer pulled 6 blocks '
             '(99 MiB) from the Guard and reused 4,224 prompt tokens. After handback, the restarted engine reused them locally.</div>'
             '\n  <aside class="notes"><ul>')
    return must(h, 'and there is a fenced handoff back to the engine.</li>\n  </ul></aside>',
                'and there is a fenced handoff back to the engine.</li>\n'
                '    <li><b>On our cluster</b> (November 4; Super VL TP2 on one node; Dynamo 1.7.0.dev20261103 wheels on the workshop '
                'base): A&#8217;s EngineCore was killed and held down. A request pinned to B pulled 6 blocks / 103,809,024 bytes from '
                'A&#8217;s Guard and recorded 4,224 external-cache input tokens, with no failed deliveries. After handback, the replacement '
                'A reused 4,224 of 6,050 input tokens from its own pool, with no remote deliveries.</li>\n'
                '    <li>Boundary: the first unpinned request after the fault failed with HTTP 503 (the frontend picked the dead endpoint '
                'three seconds before discovery removed it; migration was off). Not qualified: automatic failover, in-flight migration, '
                'cross-node recovery, GMS composition. The live KVCR demo has Guard installed but injects no failure, so it is not Guard '
                'evidence. Source: reports/workshop-kvcr-guard-qualification.md.</li>\n  </ul></aside>')


def guard_results(h):
    """KVCR #93: its title and maturity, as on the failover slide before it."""
    h = must(h, 'data-title="Guard results"', 'data-title="KVCR-Guard results"')
    return must(h, '<span class="kicker">KVCR-Guard</span>', '<span class="kicker">KVCR-Guard <span class="badge">in development</span></span>')


FT_NOTES = {   # ft slide index -> workshop cue, shown above the deck's developer notes
    4: ('<h4>Workshop</h4><p>Case 1 of the demo just ended with an error frame. What does the frontend keep? The prompt&#8217;s token '
        'IDs, every generated token ID, the remaining output budget and the request options; not the dead worker&#8217;s KV cache. The '
        'replay: input P, A returns o1 o2 o3 and dies, B gets P + o1 o2 o3 with 7 of 10 tokens left and rebuilds the missing state by '
        'prefill. Click <i>Send request</i>, then <i>Kill serving worker</i>, then back to the terminal for step 3, case 2.</p>'
        '<p>The settings box shows no <code>DYN_MIGRATION_MAX_SEQ_LEN</code>: our prompts average about 108K tokens and the demo sets '
        'no cap. A cap stops migration for longer requests; it does not truncate them.</p>'
        '<p><b>Case 2, step 3 in the terminal.</b> The answer finishes in about 17 s. In the November 9 recording the same response '
        'continued to <code>stop</code> and <code>[DONE]</code> with no stream error: 144 output tokens in 16.9 s, the first after '
        '0.18 s, and a longest gap between chunks of 0.52 s. The stream keeps naming Worker A (the field is written '
        'once), so point at the frontend&#8217;s log in the top-right pane: <code>route request failed</code> &#8594; <code>migration '
        'retry scheduled</code> with <code>migration.tokens_completed</code> (17 on November 9) &#8594; <code>Selected worker</code> on '
        'the other node &#8594; <code>route request completed</code>. Under load (November '
        '5, recorded; four streams, one engine killed): 2 of 4 completed with migration off, 4 of 4 with it on, the recap&#8217;s '
        '&#8220;4 of 4&#8221;. Then back to the slides for graceful shutdown.</p>'),
    9: ('<h4>Workshop</h4><p>The planned version of the same failure: a rollout or scale-down sends SIGTERM. The worker leaves '
        'discovery and drains; whatever is still running at the Kubernetes deadline is cut, and migrated if migration is on. Set '
        '<code>terminationGracePeriodSeconds</code> above your longest generation. Slides only, about 1.5 minutes.</p>'),
    10: ('<h4>Workshop</h4><p>Part one of the answer to the previous slide: the weights stay in GPU memory. Keep to the diagram; the '
         'allocator details below are for questions. The parked standby is not free: the Shadow Engine paper reports 4&#8211;8 GiB '
         'more per GPU.</p>'),
    11: ('<h4>Workshop</h4><p>Part two: the initialization happened before the failure. Click <i>Kill active engine</i>. The numbers on '
         'the right are the Shadow Engine blog&#8217;s GLM-5.2 example on B200, not our cluster. Our demo is next, on a different '
         'model: Super VL still hits two GMS integration bugs. Boundary: process failures only, and the promoted engine starts with an '
         'empty KV cache.</p>'),
}


def ft_workshop_js(js):
    """Resiliency, in the ft deck's script: the Shadow results chart (#113) says whose numbers they are and what its third pair
    counts, the cover's maturity notes match the rest of the deck (KVCR itself is an early release, see the KVCR section; our
    Snapshot demo restores a TP2 worker), and the slides the workshop shows get a cue above their developer notes."""
    js = must(js, "'GLM-5.2 · B200 · 2 workers, one killed'", "'Blog example · GLM-5.2 · B200 TP8 · 2 workers'")
    js = must(js, "['Requests waiting > 5 s', 201, 1, '']", "['Requests with TTFT > 5 s, of about 400', 201, 1, '']")
    js = must(js, 'Dynamo Snapshot (single-GPU vLLM/SGLang).', 'Dynamo Snapshot (single node; single- and multi-GPU).')
    js = must(js, '<b>In development</b>: KVCR / KVCR-Guard, GMS-managed KV cache.',
              '<b>In development</b>: KVCR-Guard, GMS-managed KV cache. (KVCR itself is an early release.)')
    return js + '\n' + ''.join(f'NOTES[{i}].h = {json.dumps(h)} + NOTES[{i}].h;\n' for i, h in FT_NOTES.items())


KVCR_SUBAGENT_NOTES = (
    '<p><b>Back to the question the router section left open.</b> The main agent&#8217;s context sits on A, A is busy, and B has room. The '
    'router can wait for A or recompute the whole context on B. KVCR adds a third option: copy the context to B.</p>'
    '<ul><li>Step 1: the harness announces a subagent fork. Harness hints are roadmap.</li>'
    '<li>Step 2: the router sends the request to B with a copy hint. Router-to-KVCR hints are experimental in Dynamo 1.5.</li>'
    '<li>Step 3: KVCR copies S1 from A&#8217;s host pool (G2) into B&#8217;s, and B loads it into HBM for the request instead of '
    'recomputing it.</li></ul>'
    '<p>The demo, next, has this shape: the main agent reads repository A (58K tokens) on A, and B pulls its pages from A over EFA '
    'instead of recomputing them. There we pin the requests by hand.</p>')


def kvcr_subagent_case(h):
    """KVCR #95 "Copy", after the overview, becomes the subagent case that leads into the demo (outline 2.4). Its harness panel is roadmap and the router's copy
    decision rides on experimental hints, so both are marked; the context size matches the demo's repository."""
    h = must(h, 'data-title="Copy"', 'data-title="The subagent case"')
    h = must(h, '<span class="kicker">Primitives · Copy</span>', '<span class="kicker">KVCR · the subagent case</span>')
    h = must(h, '>48k / 2k<', '>58k / 2k<')
    h = must(h, '<text class="hs" x="18" y="30">Agent harness</text>',
             '<text class="hs" x="18" y="30">Agent harness</text><rect x="150" y="12" width="84" height="26" rx="13" '
             'style="fill:none;stroke:var(--dim)"/><text class="m" x="192" y="30" text-anchor="middle">roadmap</text>')
    h = must(h, 'picks: copy</text></g>',
             'picks: copy</text><text class="m" x="830" y="92" text-anchor="middle">router hints: experimental</text></g>')
    return re.sub(r'<aside class="notes">.*?</aside>', lambda m: '<aside class="notes">' + KVCR_SUBAGENT_NOTES + '</aside>', h,
                  count=1, flags=re.S)


def kvcr_reported_results(h):
    """KVCR #92 follows the live demo: results on real workloads, AgentX (the workshop's benchmark family) first, and whose numbers
    they are."""
    h = must(h, 'data-title="Results"', 'data-title="Results on real workloads"')
    h = must(h, '<h2>KVCR results so far</h2>', '<h2>What it buys on real workloads, so far</h2>')
    h = must(h, '<p class="dim res-sub">Early results from benchmarks and production.</p>',
             '<p class="dim res-sub">Our demo showed the mechanism. These are early results reported by the KVCR team, on their '
             'setups.</p>')
    start = h.index('<div class="rmg">') + len('<div class="rmg">')
    end = h.index('\n    </div>\n  </div>', start)
    lead, *cards = re.split(r'(?=<div class="card rm">)', h[start:end])
    if len(cards) != 4 or 'AgentX' not in cards[2]:
        raise SystemExit('build: kvcr results: unexpected card layout')
    h = h[:start] + lead + ''.join(cards[i].rstrip() + '\n      ' for i in (2, 0, 1, 3)).rstrip() + h[end:]
    return must(h, '<aside class="notes">',
                '<aside class="notes"><p><b>Workshop:</b> after the demo. Lead with AgentX, the benchmark family our workload comes '
                'from. These are the KVCR team&#8217;s numbers on their setups, and its notes below say baselines and setups are still '
                'being confirmed: confirm them with the KVCR team before KubeCon.</p>')


INTRO_KVCR_STATUS = (
    '<div class="rt-rg"><div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center">'
    '<span class="chip"><b>KVCR 0.1.1</b>&#160;early release</span>'
    '<span class="chip"><b>Router-to-KVCR hints</b>&#160;experimental, Dynamo 1.5</span>'
    '<span class="chip"><b>KVCR-Guard</b>&#160;in development</span></div></div>')


def intro_kvcr(h):
    """Intro deck "KVCR · KV Cache Runner": the one-slide overview that opens the KVCR section. Its results row gives way to each piece's maturity (the
    results follow the demo, Guard's are in resiliency), and its deep-dive link goes."""
    h = must(h, '<span class="kicker">Memory management</span>', '<span class="kicker">KVCR</span>')
    h = must(h, '<span>hints say what to copy, move, prefetch or drop</span>',
             '<span>hints say what to copy, move, prefetch or drop (experimental)</span>')
    h = replace_between(h, '<div class="rt-rg">', '\n  </div>\n</section>', INTRO_KVCR_STATUS, label='intro kvcr results row')
    return must(h, '\n</section>',
                '<aside class="notes"><p>The whole picture in one slide: the router decides where KV should be, KVCR on each worker '
                'moves it peer to peer over NIXL across hosts and tiers, and a KVCR-Guard sidecar keeps the host pool alive when the '
                'engine dies. In the demo, B pulls pages from A&#8217;s host pool: the dashed arrow. Next, the case it is for: a '
                'subagent whose context sits on a busy worker.</p>'
                '<p>Maturity, as on the strip: KVCR is an early release (0.1.1 on PyPI), router hints are experimental, Guard is in '
                'development and comes back in resiliency.</p></aside>\n</section>')


SLIDE_PATCHES = {('kvcr', 1): [patch_kvcr_requirements], ('ft', 4): [migration_no_seq_cap], ('ft', 10): [gms_standby_cost],
                 ('ft', 8): [mark_fix], ('planner', 10): [planner_inline_use], ('mx', 2): [mx_part_label],
                 ('mx', 3): [mx_peer_discovery], ('kvcr', 6): [guard_failover], ('kvcr', 9): [guard_results],
                 ('kvcr', 11): [kvcr_subagent_case], ('kvcr', 8): [kvcr_reported_results], ('intro', 11): [intro_kvcr],
                 ('intro', 14): [intro_nixl],
                 ('router', 6): [router_eyebrow('Deep dive 1 · Performance <span class="step">1/4</span>', 'The router · performance')],
                 ('router', 7): [router_eyebrow('Deep dive 1 · Performance <span class="step">2/4</span>', 'The router · performance')],
                 ('router', 14): [admission_title],
                 ('router', 15): [gates_heading, router_eyebrow('Deep dive 3 · Admission control <span class="step">1/5</span>', 'Admission control')],
                 ('router', 21): [policy_file_acts], ('mx', 6): [snapshot_part_label], ('mx', 8): [snapshot_saved_teaser],
                 ('mx', 9): [together_part_label]}


def mx_no_future_plan(markup):
    """ModelExpress + Snapshot: drop the "Future plan" stamps (.fp) and badges (.fpb) everywhere."""
    out, n = re.subn(r'(<section class="slide[^"]*?) fp(")', r'\1\2', markup)
    if n != 5 or ' fp"' in out:
        raise SystemExit(f'build: mx: expected 5 "Future plan" stamps, replaced {n}')
    out = must(out, ' <span class="fpb">Future plan</span>', '', count=2)
    return out


DECK_PATCHES = {'mx': [mx_no_future_plan]}   # applied to the whole deck markup before it is split into slides


FONTS = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap'


# ----------------------------------------------------------------------------- helpers
def must(src, old, new, count=1, label=''):
    n = src.count(old)
    if n != count:
        raise SystemExit(f'build: expected {count} occurrence(s) of {label or old[:60]!r}, found {n}')
    return src.replace(old, new)


def cut_between(src, start, end, keep_end=False, label=''):
    """Remove text from `start` (inclusive) to `end` (exclusive unless keep_end)."""
    i = src.find(start)
    if i < 0:
        raise SystemExit(f'build: start marker not found: {label or start[:60]!r}')
    j = src.find(end, i + len(start))
    if j < 0:
        raise SystemExit(f'build: end marker not found: {label or end[:60]!r}')
    if not keep_end:
        j += len(end)
    return src[:i] + src[j:]


def replace_between(src, start, end, new, label=''):
    """Replace text from `start` (inclusive) up to `end` (exclusive) with `new`."""
    i = src.find(start)
    if i < 0:
        raise SystemExit(f'build: start marker not found: {label or start[:60]!r}')
    j = src.find(end, i + len(start))
    if j < 0:
        raise SystemExit(f'build: end marker not found: {label or end[:60]!r}')
    return src[:i] + new + src[j:]


def style_blocks(html):
    return re.findall(r'<style>(.*?)</style>', html, flags=re.S)


def script_blocks(html):
    """Inline <script> blocks (no src) in document order."""
    return re.findall(r'<script>(.*?)</script>', html, flags=re.S)


# ----------------------------------------------------------------------------- CSS scoping
def strip_comments(css):
    out, i, n = [], 0, len(css)
    while i < n:
        c = css[i]
        if c in '"\'':
            j = i + 1
            while j < n and css[j] != c:
                if css[j] == '\\':
                    j += 1
                j += 1
            out.append(css[i:j + 1])
            i = j + 1
            continue
        if css.startswith('/*', i):
            j = css.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _skip_str(s, j):
    q = s[j]
    j += 1
    while j < len(s) and s[j] != q:
        if s[j] == '\\':
            j += 1
        j += 1
    return j + 1


def parse_css(css):
    nodes, i, n = [], 0, len(css)
    while i < n:
        while i < n and css[i].isspace():
            i += 1
        if i >= n:
            break
        if css[i] == '}':  # stray close; skip
            i += 1
            continue
        j, depth = i, 0
        while j < n:
            c = css[j]
            if c in '"\'':
                j = _skip_str(css, j)
                continue
            if c in '([':
                depth += 1
            elif c in ')]':
                depth -= 1
            elif depth == 0 and c in '{;}':
                break
            j += 1
        if j >= n:
            break
        prelude = css[i:j].strip()
        if css[j] == ';':
            nodes.append(('stmt', prelude))
            i = j + 1
            continue
        if css[j] == '}':
            i = j
            continue
        k, depth = j + 1, 1
        while k < n and depth > 0:
            c = css[k]
            if c in '"\'':
                k = _skip_str(css, k)
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        if prelude.startswith('@'):
            name = re.split(r'[\s(]', prelude, maxsplit=1)[0].lower()
            if name in ('@media', '@supports', '@container', '@layer', '@document'):
                nodes.append(('at', prelude, parse_css(body)))
            elif name.endswith('keyframes'):
                nodes.append(('kf', prelude, body))
            else:
                nodes.append(('raw', prelude, body))
        else:
            nodes.append(('rule', prelude, body))
        i = k
    return nodes


def split_top(s, sep=','):
    parts, cur, depth, i, n = [], [], 0, 0, len(s)
    while i < n:
        c = s[i]
        if c in '"\'':
            j = _skip_str(s, i)
            cur.append(s[i:j])
            i = j
            continue
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        if c == sep and depth == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append(''.join(cur))
    return parts


def first_compound(sel):
    depth, i, n = 0, 0, len(sel)
    while i < n:
        c = sel[i]
        if c in '"\'':
            i = _skip_str(sel, i)
            continue
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif depth == 0 and (c.isspace() or c in '>+~'):
            return sel[:i], sel[i:]
        i += 1
    return sel, ''


ROOTISH = re.compile(r'^(html|:root|body)(?![\w-])')


def scope_one(sel, cls):
    sel = sel.strip()
    if not sel:
        return sel
    first, rest = first_compound(sel)
    m = ROOTISH.match(first)
    if m:
        extra = first[m.end():]
        r = rest.lstrip()
        if re.match(r'body(?![\w-])', r):
            f2, r2 = first_compound(r)
            if f2 == 'body':
                rest = r2
        if extra == '':
            return f'.{cls}' + rest
        return f'{m.group(1)}{extra} :where(.{cls})' + rest
    return f':where(.{cls}) ' + sel


def scope_selector_list(sel_list, cls):
    return ','.join(scope_one(s, cls) for s in split_top(sel_list, ','))


def rename_anim(body, names, prefix):
    if not names:
        return body

    def fix(m):
        val = m.group(2)
        for nm in names:
            val = re.sub(r'(?<![\w-])' + re.escape(nm) + r'(?![\w-])', prefix + '-' + nm, val)
        return m.group(1) + val

    return re.sub(r'((?:^|[;{\s])animation(?:-name)?\s*:\s*)([^;}]*)', fix, body)


def serialize(nodes, cls, kfnames, prefix):
    out = []
    for nd in nodes:
        t = nd[0]
        if t == 'stmt':
            out.append(nd[1] + ';')
        elif t == 'rule':
            out.append(scope_selector_list(nd[1], cls) + '{' + rename_anim(nd[2], kfnames, prefix) + '}')
        elif t == 'at':
            out.append(nd[1] + '{' + serialize(nd[2], cls, kfnames, prefix) + '}')
        elif t == 'kf':
            m = re.match(r'(@[\w-]*keyframes)\s+([\w-]+)', nd[1])
            out.append(f'{m.group(1)} {prefix}-{m.group(2)}{{{nd[2]}}}')
        else:
            out.append(nd[1] + '{' + nd[2] + '}')
    return '\n'.join(out)


def scope_css(css, sid):
    css = strip_comments(css)
    kfnames = set(re.findall(r'@[\w-]*keyframes\s+([\w-]+)', css))
    nodes = parse_css(css)
    return serialize(nodes, f'd-{sid}', kfnames, sid)


# ----------------------------------------------------------------------------- markup helpers
def fix_links(markup):
    markup = markup.replace('href="aisim.html"', 'href="https://ai-dynamo.org/slides/aisim.html"')

    def tag(m):
        t = m.group(0)
        if 'href="http' in t and 'target=' not in t:
            t = t[:-1] + ' target="_blank" rel="noopener">'
        return t

    return re.sub(r'<a\b[^>]*>', tag, markup)


VOID_TAGS = {'br', 'hr', 'img', 'input', 'meta', 'link', 'use', 'path', 'rect', 'circle', 'ellipse', 'line',
             'polyline', 'polygon', 'stop', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}


def drop_stray_closes(html, label):
    """The source decks parsed each slide with innerHTML, where an unmatched close tag is ignored.
    In a static document it would close an ancestor (the deck container), so remove such tags."""
    out, pos, stack, dropped = [], 0, [], 0
    for m in re.finditer(r'<(/?)([a-zA-Z][\w-]*)([^>]*)>', html):
        close, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if tag in VOID_TAGS or attrs.rstrip().endswith('/'):
            continue
        if not close:
            stack.append(tag)
            continue
        if stack and stack[-1] == tag:
            stack.pop()
        elif tag in stack:
            while stack and stack[-1] != tag:
                stack.pop()
            stack.pop()
        else:  # stray close tag: drop it
            out.append(html[pos:m.start()])
            pos = m.end()
            dropped += 1
    out.append(html[pos:])
    if dropped:
        print(f'  note: dropped {dropped} stray close tag(s) in {label}')
    if stack:
        raise SystemExit(f'build: unclosed tags {stack} in {label}')
    return ''.join(out)


def eval_slides(js_code, name):
    """Evaluate a `const slides = [...]` declaration (plus helpers) in Node and return the HTML strings."""
    f = WORK / f'slides-{name}.js'
    f.write_text(js_code + '\nprocess.stdout.write(JSON.stringify(slides));\n')
    r = subprocess.run(['node', str(f)], capture_output=True, text=True, cwd=str(WORK))
    if r.returncode != 0:
        raise SystemExit(f'build: node failed for {name}:\n{r.stderr}')
    slides = json.loads(r.stdout)
    return [drop_stray_closes(s, f'{name} slide {i + 1}') for i, s in enumerate(slides)]


def node_check(js, name):
    f = WORK / f'check-{name}.js'
    f.write_text(js)
    r = subprocess.run(['node', '--check', str(f)], capture_output=True, text=True, cwd=str(WORK))
    if r.returncode != 0:
        raise SystemExit(f'build: syntax error in generated script {name}:\n{r.stderr}')


def generic_js_rewrites(js):
    js = js.replace('document.getElementById(', '__$(')
    js = js.replace('document.querySelectorAll(', '__root.querySelectorAll(')
    js = js.replace('document.querySelector(', '__root.querySelector(')
    js = js.replace("document.addEventListener('click',", "__root.addEventListener('click',")
    js = js.replace('getComputedStyle(document.documentElement)', 'getComputedStyle(__root)')
    return js


def wrap_js(sid, body, register):
    return (f"/* ===================== section: {sid} ===================== */\n"
            f"(function(){{\n"
            f"const __root = document.getElementById('sec-{sid}');\n"
            f"const __$ = id => __root.querySelector('#' + CSS.escape(String(id)));\n"
            f"const __on = () => __root.classList.contains('on');\n"
            f"const __goLocal = i => DW.goLocal('{sid}', i);\n"
            f"{body}\n"
            f"{register}\n"
            f"}})();\n")


# ----------------------------------------------------------------------------- per-family builders
def build_family_a(sec, html):
    sid = sec['id']
    css = '\n'.join(style_blocks(html))
    # markup: markers svg .. </main> (+ closing stage div)
    i = html.index('<svg width="0" height="0"')
    j = html.index('</main>') + len('</main>')
    markup = html[i:j]
    if '<div id="stage">' in markup:
        markup += '</div>'
    scripts = script_blocks(html)
    assert "var slides=[].slice.call(document.querySelectorAll('.slide'));" in scripts[0], sid
    keep = scripts[1:]
    js = '\n'.join(keep)
    # the shrink-to-fit helper measured the deck's own bottom bar; use the merged deck's bar
    if "var nav=document.querySelector('.chrome')" in js:
        js = must(js, "var nav=document.querySelector('.chrome')", "var nav=DW.chromeEl()")
    if sid == 'setup':
        js = must(js, "if(b&&window.__deckGo){e.stopPropagation();window.__deckGo(+b.dataset.jump-1)}",
                  "if(b){e.stopPropagation();__goLocal(+b.dataset.jump-1)}")
    js = generic_js_rewrites(js)
    register = f"DW.register('{sid}', DW.famA(__root));"
    return css, markup, wrap_js(sid, js, register)


def build_router(sec, html, extra_js='', extra_css=''):
    sid = sec['id']
    css = '\n'.join(style_blocks(html))
    scripts = script_blocks(html)
    assert len(scripts) == 2, 'router scripts'
    main, theme = scripts
    # slides array -> static markup
    s0 = main.index('const slides = [')
    s1 = main.index('\n];', s0) + 3
    slides = eval_slides(main[s0:s1], sid)
    markup = '<div class="deck" id="deck">\n' + '\n'.join(slides) + '\n</div>'
    main = main[:s0] + main[s1:]
    # defaults (2026-11-07): "How it picks a worker" opens on cache only; "One policy file" opens on worker_selection
    markup = must(markup, '<button data-m="c">cache only</button><button data-m="l">load only</button><button data-m="b" class="on">cache + load (Dynamo)</button>',
                  '<button data-m="c" class="on">cache only</button><button data-m="l">load only</button><button data-m="b">cache + load (Dynamo)</button>')
    markup = must(markup, '<button data-y="0" class="on">router:</button><button data-y="1">policy_classes:</button><button data-y="2">worker_selection:</button>',
                  '<button data-y="0">router:</button><button data-y="1">policy_classes:</button><button data-y="2" class="on">worker_selection:</button>')
    main = must(main, "let m = 'b';", "let m = 'c';")
    main = must(main, "seg('yamlSeg', d => r(+d.y)); r(0);", "seg('yamlSeg', d => r(+d.y)); r(2);")
    # text and notes that pointed at the source deck's gate slides and acts (2026-11-08); the three "One policy file" tabs first
    main = must(main, 'Shared router behavior: Act 1 and Act 2 settings that used to be scattered',
                'Shared router behavior: KV events, active-block tracking and tier weights, which used to be scattered')
    main = must(main, 'Act 3: the queues, how they share capacity, and the admission plugin.',
                'Admission control: the queues, how they share capacity, and the admission plugin.')
    main = must(main, 'The cost model from Act 1 with its knobs, assigned per stage.', 'The cost model with its knobs, assigned per stage.')
    main = must(main, 'The next four slides are those four gates.',
                'The workshop skips the gate slides: the next four are session-aware admission, a custom admission decision for agents.')
    main = must(main, 'collects everything from Acts 1–3 in one versionable file.',
                'collects the cost knobs, the busy thresholds and the admission classes in one versionable file.')
    main = must(main, 'which matches the disaggregated hops in Act 1.', 'which matches the two hops of disaggregated serving.')
    main = must(main, '(the Act 1 formula)', '(the default formula)')
    main = must(main, '(slide 6: the cost function.)', '(after that: the cost function.)')
    # engine replacement
    fit_src = main[main.index('function fitSlide(sl) {'):main.index('const fitAll = ')]
    engine = (
        "/* ===== ENGINE (merged deck) ===== */\n"
        "let cur = 0;\n"
        "const $ = id => __$(id);\n"
        "const deck = $('deck');\n"
        "const all = deck.querySelectorAll('.slide');\n"
        "const slideIdx = t => [...all].findIndex(s => s.dataset.title === t);\n"
        "function scaleStage() { deck.style.setProperty('--s', Math.min(innerWidth / 1440, innerHeight / 810)); }\n"
        "scaleStage(); addEventListener('resize', scaleStage);\n"
        "/* auto-fill: scale each slide's content to use the 16:9 canvas without overflowing */\n"
        "all.forEach(sl => { const f = document.createElement('div'); f.className = 'fit'; while (sl.firstChild) f.appendChild(sl.firstChild); sl.appendChild(f); if (sl.dataset.next) { const nx = document.createElement('div'); nx.className = 'nextup'; nx.innerHTML = '<b>Next →</b>' + sl.dataset.next; sl.appendChild(nx); } });\n"
        + fit_src +
        "const fitAll = () => all.forEach(fitSlide);\n"
        "function show(n) {\n"
        "  cur = Math.max(0, Math.min(n, all.length - 1));\n"
        "  all.forEach((s, i) => s.classList.toggle('active', i === cur));\n"
        "}\n\n"
    )
    main = replace_between(main, '/* ===== ENGINE ===== */', 'const fmt = n =>', engine, label='router engine')
    main = must(main, "b.onclick = () => show(slideIdx('Deep dive ' + n.slice(-1)));",
                "b.onclick = () => __goLocal(slideIdx('Deep dive ' + n.slice(-1)));")
    main = must(main, "show(Math.max(0, (parseInt(location.hash.slice(1), 10) || 1) - 1), false);\n", "")
    # "How the router sees the cache": the arrow keys step the animation (the slide's own buttons keep working)
    main = must(main, "$('k5Next').onclick = () => { if (k < STEPS.length - 1) { k++; render(k, true); } };",
                "$('k5Next').onclick = () => { if (k < STEPS.length - 1) { k++; render(k, true); DW.updateChrome(); } };")
    main = must(main, "$('k5Back').onclick = () => { if (k > 0) { k--; render(k, false); } };",
                "$('k5Back').onclick = () => { if (k > 0) { k--; render(k, false); DW.updateChrome(); } };\n"
                "  __STEP['How the router sees the cache'] = {"
                " next() { if (k < STEPS.length - 1) { k++; render(k, true); return true; } return false; },"
                " prev() { if (k > 0) { k--; render(k, false); return true; } return false; },"
                " info() { return [STEPS.length - 1, k]; },"
                " set(n) { k = Math.max(0, Math.min(n, STEPS.length - 1)); render(k, false); } };")
    main = must(main, "b.onclick = () => { k = +b.dataset.i; render(k, false); });",
                "b.onclick = () => { k = +b.dataset.i; render(k, false); DW.updateChrome(); });")
    # theme script: drop theme + key handling, keep the view toggles / service-class stepper
    theme = cut_between(theme, 'function setTheme(d){', "toggleTheme();});\n", label='router theme block')
    js = 'const __STEP = {};  /* data-title -> {next, prev, info, set}: slides whose animation the arrow keys drive */\n' \
         + generic_js_rewrites(main + '\n' + theme) + '\n' + extra_js
    register = ("DW.register('router', { root: __root, slides: [...all],"
                " show(i, atEnd) { show(i); const st = __STEP[all[cur].dataset.title]; if (st) st.set(atEnd ? st.info()[0] : 0); },"
                " next() { const st = __STEP[all[cur].dataset.title]; return !!(st && st.next()); },"
                " prev() { const st = __STEP[all[cur].dataset.title]; return !!(st && st.prev()); },"
                " stepInfo() { const st = __STEP[all[cur].dataset.title]; return st ? st.info() : [0, 0]; },"
                " notes: i => NOTES[all[i].dataset.title] || '' });")
    return css + '\n' + extra_css, markup, wrap_js(sid, js, register)


def build_ft(sec, html):
    sid = sec['id']
    css = '\n'.join(style_blocks(html))
    scripts = script_blocks(html)
    assert len(scripts) == 6, f'ft scripts: {len(scripts)}'
    s_slides, s_engine, s_demos1, s_track, s_demos2, s_notes = scripts
    s0 = s_slides.index('const slides = [')
    s1 = s_slides.index('\n];', s0) + 3
    slides = eval_slides(s_slides[s0:s1], sid)
    markup = ('<div class="viewport"><div class="stage" id="deck"><div class="ft-track" id="ftTrack" hidden></div>\n'
              + '\n'.join(slides) + '\n</div></div>')
    engine = (
        "/* ================= Slide engine (merged deck) ================= */\n"
        "let cur = 0;\n"
        "const $ = id => __$(id);\n"
        "const deck = $('deck');\n"
        "const all = deck.querySelectorAll('.slide');\n"
        "let __renderTrack = null;\n"
        "function fitStage() { const s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080); deck.style.setProperty('--s', s); }\n"
        "window.addEventListener('resize', fitStage); fitStage();\n"
        "function show(n) {\n"
        "  cur = Math.max(0, Math.min(n, all.length - 1));\n"
        "  all.forEach((s, i) => s.classList.toggle('active', i === cur));\n"
        "  const s = all[cur];\n"
        "  if (__renderTrack) __renderTrack(s.dataset.ft);\n"
        "  if (s._onEnter && s._prev !== true) s._onEnter.forEach(f => { try { f(); } catch (_) {} });\n"
        "  all.forEach(x => { x._prev = x === s; });\n"
        "}\n"
        "function isActiveSlide(el) { const s = el && el.closest('.slide'); return !!s && s.classList.contains('active'); }\n\n"
    )
    s_engine = replace_between(s_engine, '/* ================= Slide engine ================= */',
                               '/* ================= Shared demo helpers ================= */', engine, label='ft engine')
    # unique SVG marker / gradient ids (the router deck has copies of the same widgets)
    s_engine = must(s_engine, "id: id + '-ah'", "id: 'ft-' + id + '-ah'")
    s_engine = must(s_engine, "svg._ah = 'url(#' + id + '-ah)';", "svg._ah = 'url(#ft-' + id + '-ah)';")
    s_demos1 = must(s_demos1, "id: 'gdisc2'", "id: 'ft-gdisc2'")
    s_demos1 = must(s_demos1, "fill:url(#gdisc2)", "fill:url(#ft-gdisc2)")
    s_track = must(s_track, "window.renderTrack = function (ft) {", "__renderTrack = function (ft) {")
    s_track = must(s_track, "window.renderTrack(all[cur] && all[cur].dataset.ft);", "__renderTrack(all[cur] && all[cur].dataset.ft);")
    s_demos2 = must(s_demos2, "show(slideIndexFromHash() ?? 0, { syncHash: false });\n", "")
    s_notes = replace_between(s_notes, "(function () {\n  const panel = $('notes');", "})();", "", label='ft notes ui')
    s_notes = must(s_notes, "})();", "", count=1) if s_notes.count('})();') == 1 else s_notes
    js = generic_js_rewrites('\n'.join([s_engine, s_demos1, s_track, s_demos2, s_notes]))
    js = ft_workshop_js(js)
    register = ("DW.register('ft', { root: __root, slides: [...all], show,"
                " notes: i => NOTES[i] ? NOTES[i].h : '', title: i => (NOTES[i] && NOTES[i].t) || '' });")
    return css, markup, wrap_js(sid, js, register)


def build_mx(sec, html):
    sid = sec['id']
    css = '\n'.join(style_blocks(html))
    scripts = script_blocks(html)
    assert len(scripts) == 1, 'mx scripts'
    main = scripts[0]
    # helper functions + slides array -> static markup
    h0 = main.index('function treeSVG(){')
    s0 = main.index('const slides = [')
    s1 = main.index('\n];', s0) + 3
    slides = eval_slides(main[h0:s1], sid)
    d0 = html.index('<svg width="0" height="0"')
    d1 = html.index('</defs></svg>') + len('</defs></svg>')
    markup = html[d0:d1] + '\n<div class="deck" id="deck">\n' + '\n'.join(slides) + '\n</div>'
    main = main[:main.index('/* ===================== SVG generators used inside slides')] + main[s1:]
    engine = (
        "/* ===================== Engine (merged deck) ===================== */\n"
        "let cur = 0;\n"
        "const $ = id => __$(id);\n"
        "const deck = $('deck');\n"
        "let __onSlideChange = null;\n"
        "function fitDeck(){const s=Math.min(window.innerWidth/1920,window.innerHeight/1080);deck.style.transform='translate(-50%,-50%) scale('+s+')';}\n"
        "window.addEventListener('resize',fitDeck);fitDeck();\n"
        "let all = deck.querySelectorAll('.slide');\n"
        "function show(n) {\n"
        "  cur = Math.max(0, Math.min(n, all.length - 1));\n"
        "  all.forEach((s, i) => { s.classList.toggle('active', i === cur); s.classList.toggle('visible', i === cur); });\n"
        "  if (__onSlideChange) __onSlideChange(cur);\n"
        "}\n\n"
    )
    main = replace_between(main, '/* ===================== Engine ===================== */',
                           '/* ===================== Shared model data ===================== */', engine, label='mx engine')
    main = must(main, "if(cur===SLIDE_B){", "if(__on()&&cur===SLIDE_B){")
    main = must(main, "if(cur===SLIDE_G){", "if(__on()&&cur===SLIDE_G){")
    main = must(main, "window.onSlideChange=i=>{renderNotes();if(i!==12&&eAuto){clearInterval(eAuto);eAuto=null;renderE(eI)}};",
                "__onSlideChange=i=>{if(i!==12&&eAuto){clearInterval(eAuto);eAuto=null;renderE(eI)}};")
    main = must(main, "function renderNotes(){const p=$('notesPanel');if(p)p.innerHTML=SPEAKER_NOTES[cur]||'<p>No notes for this slide.</p>'}\n", "")
    main = must(main, "function toggleNotes(){const p=$('notesPanel');p.classList.toggle('open');renderNotes()}\n", "")
    main = must(main, "$('notesBtn').onclick=toggleNotes;\n", "")
    main = must(main, "document.addEventListener('keydown',e=>{if((e.key==='n'||e.key==='N')&&!isInteractiveTarget(e.target))toggleNotes()});\n", "")
    main = snapshot_saved_notes(mx_notes(main))
    # the notes headers carry the source deck's slide numbers and "Part N" labels, which match neither our numbering nor sections
    main, n = re.subn(r'<h4>\d+ · (?:Part \d: )?', '<h4>', main)
    if n != 16:
        raise SystemExit(f'mx notes headers: expected 16, found {n}')
    main = cut_between(main, '/* ===================== Theme toggle (light default) ===================== */', '})();\n', label='mx theme')
    main = must(main, "show(slideIndexFromHash() ?? (window.START_SLIDE || 0), { syncHash: false });\n", "")
    js = generic_js_rewrites(main)
    register = ("DW.register('mx', { root: __root, slides: [...all], show,"
                " notes: i => SPEAKER_NOTES[i] || '',"
                " onHide(){ if(eAuto){clearInterval(eAuto);eAuto=null;renderE(eI)} } });")
    return css, markup, wrap_js(sid, js, register)


def build_planner(sec, html):
    """ai-dynamo.org/slides/planner-grove.html: static <section class="slide"> markup on a 1600x900 stage. Its own engine,
    notes drawer, theme and simulator scripts are dropped; the shared Family A adapter drives the slides, plus the deck's
    shrink-to-fit of .inner for the active slide."""
    sid = sec['id']
    css = '\n'.join(style_blocks(html))
    i = html.index('<svg width="0" height="0"')
    j = html.index('<nav class="hud"')
    markup = cut_between(html[i:j], '<div class="foot">', '</div>', label='planner foot')
    js = (
        "const __stage = __root.querySelector('.stage');\n"
        "const __fit = () => { __stage.style.transform = 'translate(-50%,-50%) scale(' + Math.min(innerWidth / 1600, innerHeight / 900) + ')'; };\n"
        "__fit(); addEventListener('resize', __fit);\n"
        "function __fitActive() {\n"
        "  const sl = __root.querySelector('.slide.active'), inner = sl && sl.querySelector('.inner'); if (!inner) return;\n"
        "  inner.style.transform = '';\n"
        "  const cs = getComputedStyle(sl), avail = sl.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom), need = inner.offsetHeight;\n"
        "  if (need > avail) inner.style.transform = 'scale(' + (avail / need).toFixed(4) + ')';\n"
        "}\n"
        "const __a = DW.famA(__root), __show = __a.show;\n"
        "__a.show = (i, atEnd) => { __show(i, atEnd); requestAnimationFrame(__fitActive); };\n"
        "addEventListener('resize', () => { if (__root.classList.contains('on')) __fitActive(); });")
    register = f"DW.register('{sid}', __a);"
    return css, markup, wrap_js(sid, js, register)


# ----------------------------------------------------------------------------- host page
# ----------------------------------------------------------------------------- native (authored) sections
def load_module(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_native(sec):
    """A section authored for this deck (no ai-dynamo.org source). Its module provides CSS, SLIDES and JS;
    slides use the Family A conventions (data-title, data-steps, [data-s] build steps, <aside class="notes">)."""
    mod = load_module(sec['id'] if sec['id'] != 'fund' else 'fundamentals')
    sid = sec['id']
    slides = [drop_stray_closes(h, f'{sid} slide {i}') for i, h in enumerate(mod.render_slides())]
    markup = '<div class="fstage">\n' + '\n'.join(slides) + '\n</div>'
    js = mod.JS
    register = f"DW.register('{sid}', DW.famA(__root));"
    return mod.CSS, markup, wrap_js(sid, js, register)


HOST_CSS = r"""
.sec .slide aside.notes{display:none!important}
:root{--dw-bg:#eef2f1;--dw-surface:#ffffff;--dw-text:#12191c;--dw-dim:#56636a;--dw-line:rgba(16,24,28,.13);
  --dw-green:#5e9a00;--dw-green-fill:#76b900;--dw-green-ink:#4a7a00;--dw-cyan:#1597b3;
  --dw-shadow:0 1px 2px rgba(16,24,28,.06),0 8px 24px rgba(16,24,28,.08);
  --dw-hero:radial-gradient(ellipse at 15% 35%,rgba(118,185,0,.18),transparent 50%),radial-gradient(ellipse at 65% 72%,rgba(62,199,224,.16),transparent 50%),linear-gradient(180deg,#f9fbfa,#eef2f1);
  --dw-nav-bg:rgba(255,255,255,.88);--dw-nav-line:rgba(16,24,28,.18);color-scheme:light}
html.dark{--dw-bg:#07090a;--dw-surface:#11171a;--dw-text:#e8eef0;--dw-dim:#8f9ca3;--dw-line:rgba(255,255,255,.12);
  --dw-green:#76b900;--dw-green-fill:#76b900;--dw-green-ink:#9fd44a;--dw-cyan:#3ec7e0;
  --dw-shadow:0 2px 4px rgba(0,0,0,.2),0 12px 32px rgba(0,0,0,.22);
  --dw-hero:radial-gradient(ellipse at 15% 35%,rgba(118,185,0,.14),transparent 50%),radial-gradient(ellipse at 65% 72%,rgba(62,199,224,.12),transparent 50%),linear-gradient(180deg,#080b0c,#06080a);
  --dw-nav-bg:rgba(20,28,32,.75);--dw-nav-line:rgba(255,255,255,.16);color-scheme:dark}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:100%;height:100%;overflow:hidden;background:var(--dw-bg);color:var(--dw-text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.sec{position:absolute;inset:0;opacity:0;pointer-events:none;z-index:1;transition:opacity .3s ease}
.sec.on{opacity:1;pointer-events:auto;z-index:2}

/* cover + section dividers (1920x1080 canvas, scaled) */
.d-host{background:var(--dw-bg)}
.d-host .hstage{position:absolute;left:50%;top:50%;width:1920px;height:1080px;transform:translate(-50%,-50%) scale(var(--hs,.5));overflow:hidden;background:var(--dw-bg)}
.d-host .slide{position:absolute;inset:0;overflow:hidden;opacity:0;pointer-events:none;transition:opacity .4s ease;background:var(--dw-hero);padding:80px 150px 120px;display:flex;flex-direction:column;justify-content:center;gap:22px;color:var(--dw-text)}
.d-host .slide.active{opacity:1;pointer-events:auto}
.d-host .kicker{font:500 20px "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.18em;text-transform:uppercase;color:var(--dw-green-ink)}
.d-host h1{font:800 104px/1 Inter,sans-serif;letter-spacing:-.03em;max-width:1400px;text-wrap:balance}
.d-host .bar{width:140px;height:10px;border-radius:5px;background:linear-gradient(90deg,#76b900,#3ec7e0)}
.d-host .desc{font-size:34px;line-height:1.4;color:var(--dw-dim);max-width:1250px;text-wrap:pretty}
.d-host .divnum{position:absolute;right:110px;bottom:40px;font:800 320px/0.85 Inter,sans-serif;letter-spacing:-.05em;opacity:.10;color:var(--dw-green-ink);pointer-events:none}
.d-host .agenda{margin-top:10px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px 56px;max-width:1340px;list-style:none}
.d-host .agenda li{font-size:23px;line-height:1.3;display:flex;gap:14px;align-items:baseline;min-width:0}
.d-host .agenda li span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.d-host .agenda li b{font:600 17px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-green-ink);min-width:36px}
.d-host .agenda li.more{color:var(--dw-dim)}
.d-host .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin-top:20px;max-width:1640px}
.d-host .card{background:var(--dw-surface);border:1px solid var(--dw-line);border-top:4px solid var(--dw-green-fill);border-radius:16px;padding:22px 24px 20px;box-shadow:var(--dw-shadow);display:flex;flex-direction:column;gap:8px;cursor:pointer;transition:transform .15s,border-color .15s}
.d-host .card:hover{transform:translateY(-3px);border-color:var(--dw-green)}
.d-host .card b{font:600 15px "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.14em;color:var(--dw-green-ink)}
.d-host .card h3{font:700 26px/1.15 Inter,sans-serif;letter-spacing:-.01em}
.d-host .card p{font-size:17px;line-height:1.4;color:var(--dw-dim);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.d-host .cards.c5{grid-template-columns:repeat(5,1fr);gap:16px}.d-host .cards.c5 .card{padding:18px 20px 16px}.d-host .cards.c5 .card h3{font-size:22px}.d-host .cards.c5 .card p{font-size:15px;-webkit-line-clamp:4}

/* "FIX" marker on slides flagged for rework (build.py: mark_fix) */
.dw-fixtag{position:absolute;top:18px;right:26px;z-index:60;font:800 26px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.16em;color:#fff;background:#d7263d;padding:10px 18px 9px;border-radius:999px;box-shadow:0 2px 10px rgba(0,0,0,.25);pointer-events:none}

/* still capture mode: ?still=1 shows the slide at its final build step, without chrome or motion */
html.dw-still .dw-chrome,html.dw-still .dw-progress{display:none!important}
html.dw-still *{transition:none!important;animation-duration:0s!important;animation-delay:0s!important}

/* chrome */
.dw-chrome{position:fixed;left:0;right:0;bottom:calc(10px + env(safe-area-inset-bottom,0px));display:flex;justify-content:space-between;align-items:center;padding:0 16px;z-index:100;pointer-events:none;transition:opacity .25s}
.dw-chrome>*{pointer-events:auto}
html:fullscreen .dw-chrome{opacity:.25}html:fullscreen .dw-chrome:hover{opacity:1}
.dw-left{display:flex;align-items:center;gap:10px;height:40px;padding:0 14px;max-width:46vw;background:var(--dw-nav-bg);border:1px solid var(--dw-nav-line);border-radius:10px;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);font:500 12px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);white-space:nowrap;overflow:hidden}
.dw-left .dw-sec{color:var(--dw-green-ink);font-weight:600;letter-spacing:.08em;text-transform:uppercase;flex:none}
.dw-left .dw-title{overflow:hidden;text-overflow:ellipsis;min-width:0}
.dw-right{display:flex;gap:6px;align-items:center}
.dw-btn{font:500 13px Inter,sans-serif;height:40px;min-width:40px;padding:0 12px;color:var(--dw-dim);background:var(--dw-nav-bg);border:1px solid var(--dw-nav-line);border-radius:10px;cursor:pointer;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px)}
.dw-btn:hover{color:var(--dw-text);border-color:var(--dw-green)}
.dw-btn.on{color:var(--dw-text);border-color:var(--dw-green-fill)}
.dw-pg{font:500 13px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);min-width:78px;text-align:center;opacity:.85}
.dw-dots{display:flex;gap:4px;margin-right:6px}.dw-dots i{width:6px;height:6px;border-radius:50%;background:var(--dw-line)}.dw-dots i.on{background:var(--dw-green-fill)}
.dw-progress{position:fixed;left:0;bottom:0;height:3px;background:linear-gradient(90deg,#76b900,#3ec7e0);transition:width .4s ease;z-index:100}

/* speaker notes */
.dw-notes{visibility:hidden;position:fixed;left:50%;bottom:60px;transform:translate(-50%,calc(100% + 80px));width:min(1000px,calc(100% - 32px));max-height:44vh;overflow:auto;background:var(--dw-surface);border:1px solid var(--dw-line);border-top:4px solid var(--dw-green-fill);border-radius:16px;box-shadow:var(--dw-shadow);padding:14px 22px 20px;z-index:150;transition:transform .25s ease,visibility 0s .25s;font-size:15px;line-height:1.5;color:var(--dw-text)}
.dw-notes.open{visibility:visible;transform:translate(-50%,0);transition:transform .25s ease}
.dw-nh{display:flex;align-items:baseline;gap:12px;margin:0 0 10px;font:600 11px "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--dw-green-ink)}
.dw-nh span{color:var(--dw-dim);text-transform:none;letter-spacing:0;font:500 12px "JetBrains Mono",ui-monospace,Menlo,monospace;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dw-notes h4{font:600 11px "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--dw-green-ink);margin:12px 0 5px}
.dw-notes h4:first-child{margin-top:0}
.dw-notes p,.dw-notes li{font-size:15px;line-height:1.5;color:var(--dw-text)}
.dw-notes p{margin:0 0 8px}
.dw-notes ul,.dw-notes ol{padding-left:20px;margin:4px 0 8px;display:flex;flex-direction:column;gap:3px}
.dw-notes code{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:13px;background:rgba(127,127,127,.15);padding:1px 5px;border-radius:4px;white-space:normal;overflow-wrap:anywhere}
.dw-notes table{border-collapse:collapse;margin:6px 0 12px;font-size:14px}.dw-notes td,.dw-notes th{border:1px solid var(--dw-line);padding:4px 10px;text-align:left}
.dw-notes b{color:var(--dw-text)}.dw-notes a{color:var(--dw-green-ink)}
.dw-notes .dw-dim{color:var(--dw-dim)}
.dw-notes .tag{display:inline-block;font:600 11px "JetBrains Mono",monospace;letter-spacing:.06em;text-transform:uppercase;padding:1px 7px;border-radius:999px;border:1px solid var(--dw-line);color:var(--dw-dim);margin-left:4px}

/* overview */
.dw-ov{position:fixed;inset:0;z-index:200;display:none;flex-direction:column;background:color-mix(in srgb,var(--dw-bg) 94%,transparent);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);color:var(--dw-text)}
.dw-ov.open{display:flex}
.dw-ov-h{display:flex;align-items:center;gap:14px;padding:18px 28px 6px}.dw-ov-h b{font-size:20px}.dw-ov-h span{font:13px "JetBrains Mono",ui-monospace,Menlo,monospace;opacity:.6}.dw-ov-h .dw-btn{margin-left:auto}
.dw-ov-g{flex:1;overflow-y:auto;padding:4px 28px 28px}
.dw-ov-s{font:600 12px "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--dw-green-ink);margin:18px 0 10px;display:flex;align-items:center;gap:12px}.dw-ov-s::after{content:"";flex:1;height:1px;background:var(--dw-line)}
.dw-ov-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.dw-ov-t{text-align:left;border:1px solid var(--dw-line);border-radius:12px;background:var(--dw-surface);color:inherit;padding:12px 14px 14px;min-height:84px;cursor:pointer;display:flex;flex-direction:column;gap:6px;font:inherit;transition:transform .12s,box-shadow .12s,border-color .12s}
.dw-ov-t:hover,.dw-ov-t.sel{transform:translateY(-2px);box-shadow:var(--dw-shadow);border-color:var(--dw-green-fill)}
.dw-ov-t.cur{box-shadow:inset 0 0 0 2px var(--dw-green-fill)}
.dw-ov-n{font:700 18px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-green-ink);line-height:1}
.dw-ov-ti{font-size:14px;font-weight:600;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.dw-ov-t.div .dw-ov-ti{color:var(--dw-green-ink)}
"""

HOST_JS = r"""
window.DW = (function () {
  const SECTIONS = __SECTIONS__;
  const sections = {};           // id -> adapter
  let ENTRIES = [], cur = -1, started = false;
  const $ = id => document.getElementById(id);
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();

  /* ---------- adapter for the static decks (aiperf, kvcr) and the authored section: build steps + hooks ---------- */
  function famA(root) {
    const slides = [...root.querySelectorAll('.slide')];
    let cur = 0, step = 0;
    const maxS = s => +(s.dataset.steps || 0);
    function render() {
      slides.forEach((s, i) => s.classList.toggle('active', i === cur));
      const s = slides[cur]; s.dataset.step = step;
      s.querySelectorAll('[data-s]').forEach(e => { const k = +e.dataset.s; e.classList.toggle('on', step >= k); e.classList.toggle('now', step === k); });
      s.querySelectorAll('[data-only]').forEach(e => e.classList.toggle('on', e.dataset.only.split(' ').indexOf(String(step)) > -1));
      s.querySelectorAll('[data-goto]').forEach(b => b.setAttribute('aria-pressed', (+b.dataset.goto === step) ? 'true' : 'false'));
    }
    root.addEventListener('click', e => { const b = e.target.closest('[data-goto]'); if (b) { step = +b.dataset.goto; render(); api.updateChrome(); } });
    return {
      root, slides,
      show(i, atEnd) { cur = Math.max(0, Math.min(i, slides.length - 1)); step = atEnd ? maxS(slides[cur]) : 0; render(); },
      next() { if (step < maxS(slides[cur])) { step++; render(); return true; } return false; },
      prev() { if (step > 0) { step--; render(); return true; } return false; },
      stepInfo() { return [maxS(slides[cur]), step]; },
      notes(i) { const n = slides[i].querySelector('aside.notes'); return n ? n.innerHTML : ''; },
      title(i) { return slides[i].dataset.title || ''; }
    };
  }

  /* ---------- host adapter: cover + dividers ---------- */
  function hostAdapter() {
    const root = $('sec-host'), stage = root.querySelector('.hstage');
    const slides = [...root.querySelectorAll('.slide')];
    const fit = () => stage.style.setProperty('--hs', Math.min(innerWidth / 1920, innerHeight / 1080));
    fit(); addEventListener('resize', fit);
    return { root, slides, show(i) { slides.forEach((s, k) => s.classList.toggle('active', k === i)); }, notes(i) { return slides[i].dataset.notes || ''; }, title(i) { return slides[i].dataset.title || ''; } };
  }

  const titleOf = (a, i) => {
    if (a.title) { const t = clean(a.title(i)); if (t) return t; }
    const s = a.slides[i], h = s.querySelector('h1,h2');
    return clean(s.dataset.title) || clean(h && h.textContent) || ('Slide ' + (i + 1));
  };

  /* ---------- flattened slide list: the program decides which deck slides are shown, in which order ---------- */
  function build() {
    const host = sections.host;
    ENTRIES = [{ sec: 'host', local: 0, section: null }];
    SECTIONS.forEach((S, k) => {
      ENTRIES.push({ sec: 'host', local: k + 1, section: S, divider: true });
      const titles = [];
      S.slides.forEach(([id, i]) => {
        const a = sections[id];
        if (!a || !a.slides[i]) { console.warn('DW: missing slide', id, i); return; }
        const listed = !a.slides[i].hasAttribute('data-noagenda');   // a break slide is shown but not listed on its divider
        ENTRIES.push({ sec: id, local: i, section: S, pos: listed ? titles.length + 1 : 0 });
        if (listed) titles.push(titleOf(a, i));
      });
      S.count = titles.length;
      // agenda on the divider
      const ol = host.slides[k + 1].querySelector('.agenda');
      if (ol) {
        const MAX = 12;
        ol.innerHTML = titles.slice(0, MAX).map((t, i) => '<li><b>' + String(i + 1).padStart(2, '0') + '</b><span>' + t.replace(/</g, '&lt;') + '</span></li>').join('')
          + (titles.length > MAX ? '<li class="more"><b>+' + (titles.length - MAX) + '</b><span>more slides</span></li>' : '');
      }
    });
  }
  const entryIndex = (sec, local) => ENTRIES.findIndex(e => e.sec === sec && e.local === local);

  /* ---------- activation ---------- */
  function activate(idx, atEnd) {
    idx = Math.max(0, Math.min(idx, ENTRIES.length - 1));
    const e = ENTRIES[idx], prev = cur >= 0 ? ENTRIES[cur] : null;
    if (prev && prev.sec !== e.sec) {
      const pa = sections[prev.sec];
      pa.root.classList.remove('on'); pa.root.inert = true;
      pa.root.querySelectorAll('.slide.active').forEach(s => s.classList.remove('active', 'visible'));
      if (pa.onHide) { try { pa.onHide(); } catch (_) {} }
    }
    cur = idx;
    const a = sections[e.sec];
    if (!a.root.classList.contains('on')) { a.root.classList.add('on'); a.root.inert = false; }
    a.show(e.local, !!atEnd);
    if (document.activeElement && document.activeElement !== document.body && !document.activeElement.closest('.dw-chrome')) document.activeElement.blur();
    updateChrome(); renderNotes();
    try { history.replaceState(null, '', '#' + (idx + 1)); } catch (_) {}
  }
  const go = (i, atEnd) => activate(i, atEnd);
  function next() { const e = ENTRIES[cur], a = sections[e.sec]; if (a.next && a.next()) { updateChrome(); return; } if (cur < ENTRIES.length - 1) activate(cur + 1); }
  function prev() { const e = ENTRIES[cur], a = sections[e.sec]; if (a.prev && a.prev()) { updateChrome(); return; } if (cur > 0) activate(cur - 1, true); }
  function nextSection() { for (let i = cur + 1; i < ENTRIES.length; i++) if (ENTRIES[i].divider) return activate(i); activate(ENTRIES.length - 1); }
  function prevSection() { for (let i = cur - 1; i >= 0; i--) if (ENTRIES[i].divider || i === 0) return activate(i); }

  /* ---------- chrome ---------- */
  function updateChrome() {
    const e = ENTRIES[cur], a = sections[e.sec];
    const n = ENTRIES.length;
    $('dw-pg').textContent = (cur + 1) + ' / ' + n;
    $('dw-progress').style.width = ((cur + 1) / n * 100) + '%';
    const secName = e.section ? e.section.name : 'NVIDIA Dynamo';
    const k = (e.sec === 'host' || !e.pos) ? null : e.pos + ' / ' + e.section.count;
    $('dw-sec').textContent = secName;
    $('dw-title').textContent = (k ? k + ' · ' : '') + titleOf(a, e.local);
    const d = $('dw-dots'); d.innerHTML = '';
    if (a.stepInfo) { const [m, s] = a.stepInfo(); if (m) for (let i = 0; i <= m; i++) { const x = document.createElement('i'); if (i <= s) x.className = 'on'; d.appendChild(x); } }
  }

  /* ---------- notes ---------- */
  let notesOpen = false;
  function renderNotes() {
    if (!notesOpen) return;
    const e = ENTRIES[cur], a = sections[e.sec];
    const html = a.notes ? a.notes(e.local) : '';
    $('dw-notes-title').textContent = (cur + 1) + ' · ' + titleOf(a, e.local);
    $('dw-notes-body').innerHTML = html || '<p class="dw-dim">No notes for this slide.</p>';
    $('dw-notespanel').scrollTop = 0;
  }
  function setNotes(o) { notesOpen = o; $('dw-notespanel').classList.toggle('open', o); $('dw-notes').classList.toggle('on', o); renderNotes(); }
  const toggleNotes = () => setNotes(!notesOpen);

  /* ---------- theme ---------- */
  function applyTheme(dark) {
    const h = document.documentElement;
    h.classList.toggle('dark', dark); h.classList.toggle('light', !dark);
    h.setAttribute('data-theme', dark ? 'dark' : 'light');
    const b = $('dw-theme'); if (b) b.textContent = dark ? 'Light' : 'Dark';
    try { localStorage.setItem('dw-theme', dark ? 'dark' : 'light'); } catch (_) {}
  }
  const isDark = () => document.documentElement.classList.contains('dark');
  const toggleTheme = () => applyTheme(!isDark());

  /* ---------- full screen ---------- */
  function toggleFs() {
    try {
      if (document.fullscreenElement) document.exitFullscreen();
      else { const p = document.documentElement.requestFullscreen && document.documentElement.requestFullscreen(); if (p && p.catch) p.catch(() => {}); }
    } catch (_) {}
  }

  /* ---------- overview ---------- */
  let ovSel = 0;
  function buildOverview() {
    const g = $('dw-ov-grid'); let h = '', open = false;
    ENTRIES.forEach((e, i) => {
      const a = sections[e.sec];
      if (e.divider || i === 0) {
        if (open) h += '</div>';
        h += '<div class="dw-ov-s">' + (e.section ? ('Section ' + (SECTIONS.indexOf(e.section) + 1) + ' · ' + e.section.name) : 'Cover') + '</div><div class="dw-ov-grid">'; open = true;
      }
      h += '<div class="dw-ov-t' + (i === cur ? ' cur' : '') + (e.divider || i === 0 ? ' div' : '') + '" role="button" tabindex="0" data-i="' + i + '"><span class="dw-ov-n">' + (i + 1) + '</span><span class="dw-ov-ti">' + titleOf(a, e.local).replace(/</g, '&lt;') + '</span></div>';
    });
    if (open) h += '</div>';
    g.innerHTML = h; ovSel = cur;
  }
  const ovTiles = () => [...$('dw-ov-grid').querySelectorAll('.dw-ov-t')];
  function ovMark() { ovTiles().forEach((b, i) => b.classList.toggle('sel', i === ovSel)); const b = ovTiles()[ovSel]; if (b) b.scrollIntoView({ block: 'nearest' }); }
  function openOverview() { buildOverview(); $('dw-ov').classList.add('open'); ovMark(); }
  function closeOverview() { $('dw-ov').classList.remove('open'); }
  const ovOpen = () => $('dw-ov').classList.contains('open');

  /* ---------- input ---------- */
  function bindInput() {
    $('dw-prev').onclick = prev; $('dw-next').onclick = next;
    $('dw-notes').onclick = toggleNotes; $('dw-notes-close').onclick = () => setNotes(false);
    $('dw-theme').onclick = toggleTheme; $('dw-fs').onclick = toggleFs;
    $('dw-all').onclick = openOverview; $('dw-ov-close').onclick = closeOverview;
    $('dw-ov-grid').addEventListener('click', e => { const b = e.target.closest('.dw-ov-t'); if (!b) return; closeOverview(); go(+b.dataset.i); });
    document.querySelectorAll('[data-go-section]').forEach(c => c.addEventListener('click', () => { const i = entryIndex('host', +c.dataset.goSection + 1); if (i >= 0) go(i); }));
    document.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target, k = e.key;
      const inField = !!(t && t.closest && t.closest('input, textarea, select, [contenteditable="true"]'));
      if (ovOpen()) {
        const n = ovTiles().length;
        if (k === 'Escape') closeOverview();
        else if (k === 'Enter') { closeOverview(); go(ovSel); }
        else if (k === 'ArrowRight') ovSel = Math.min(n - 1, ovSel + 1);
        else if (k === 'ArrowLeft') ovSel = Math.max(0, ovSel - 1);
        else if (k === 'ArrowDown') ovSel = Math.min(n - 1, ovSel + 4);
        else if (k === 'ArrowUp') ovSel = Math.max(0, ovSel - 4);
        else if (k === 'o' || k === 'O' || k === 'g' || k === 'G') closeOverview();
        else return;
        e.preventDefault(); ovMark(); return;
      }
      if (inField && (k.startsWith('Arrow') || k === ' ' || k === 'Home' || k === 'End' || k.length === 1)) return;
      if (k === 'ArrowRight' || k === 'PageDown' || (k === ' ' && !(t && t.closest && t.closest('button')))) { e.preventDefault(); if (e.shiftKey) nextSection(); else next(); }
      else if (k === 'ArrowLeft' || k === 'PageUp') { e.preventDefault(); if (e.shiftKey) prevSection(); else prev(); }
      else if (k === 'Home') { e.preventDefault(); go(0); }
      else if (k === 'End') { e.preventDefault(); go(ENTRIES.length - 1); }
      else if (k === 'n' || k === 'N') toggleNotes();
      else if (k === 'f' || k === 'F') toggleFs();
      else if (k === 't' || k === 'T' || k === 'd' || k === 'D') toggleTheme();
      else if (k === 'o' || k === 'O' || k === 'g' || k === 'G') openOverview();
      else if (k === 'Escape') setNotes(false);
    });
    let tx = 0, ty = 0;
    document.addEventListener('touchstart', e => { tx = e.touches[0].clientX; ty = e.touches[0].clientY; }, { passive: true });
    document.addEventListener('touchend', e => {
      if (e.target.closest && e.target.closest('input, button, select, textarea, a, .dw-notes, .dw-ov')) return;
      const dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty;
      if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) (dx < 0 ? next : prev)();
    });
    addEventListener('hashchange', () => { const p = parseInt((location.hash || '').slice(1), 10); if (p > 0 && p - 1 !== cur && p <= ENTRIES.length) go(p - 1); });
  }

  /* ---------- start ---------- */
  function start() {
    if (started) return; started = true;
    sections.host = hostAdapter();
    build(); bindInput();
    applyTheme(isDark());
    const p = parseInt((location.hash || '').slice(1), 10);
    const still = /[?&]still=1/.test(location.search);
    if (still) document.documentElement.classList.add('dw-still');
    activate(p > 0 && p <= ENTRIES.length ? p - 1 : 0, still);
  }

  const api = {
    register(id, adapter) { sections[id] = adapter; },
    famA, start, go, next, prev, nextSection, prevSection, toggleNotes, toggleTheme, openOverview,
    goLocal(id, i) { const k = entryIndex(id, i); if (k >= 0) go(k); },
    chromeEl() { return document.querySelector('.dw-chrome'); },
    updateChrome, count: () => ENTRIES.length, current: () => cur, entries: () => ENTRIES
  };
  return api;
})();
"""

HEAD_THEME_JS = r"""
(function(){var t=null;try{t=localStorage.getItem('dw-theme')}catch(e){}var d=t==='dark',h=document.documentElement;
h.classList.toggle('dark',d);h.classList.toggle('light',!d);h.setAttribute('data-theme',d?'dark':'light');})();
"""


def host_markup():
    cards = ''.join(
        f'<div class="card" data-go-section="{k}"><b>{k + 1:02d}</b><h3>{S["name"]}</h3><p>{S["desc"]}</p></div>'
        for k, S in enumerate(PROGRAM))
    cover = (
        '<section class="slide cover" data-title="DSX OS AI Inference Workshop - Dynamo" data-notes="Cover slide for the combined deck. The sections follow in order; each starts with a divider slide.">'
        '<div class="kicker">NVIDIA Dynamo</div>'
        '<h1>DSX OS AI Inference Workshop - Dynamo</h1>'
        '<div class="bar"></div>'
        '<p class="desc">Inference fundamentals, faster replicas with ModelExpress, cache-aware routing, KV cache movement, disaggregation and autoscaling, admission control, serving through failures, and Snapshot restore.</p>'
        f'<div class="cards{" c5" if len(PROGRAM) > 8 else ""}">{cards}</div>'
        '</section>')
    divs = ''
    for k, S in enumerate(PROGRAM):
        divs += (
            f'<section class="slide divider" data-title="Section {k + 1} · {S["name"]}">'
            + ('' if S['id'] in {'fund', 'disagg', 'auto', 'adm'} else f'<div class="kicker">Section {k + 1:02d} / {len(PROGRAM):02d}</div>') +
            f'<h1>{S["name"]}</h1>'
            '<div class="bar"></div>'
            f'<p class="desc">{S["desc"]}</p>'
            + ('<ol class="agenda"></ol>' if S.get('agenda', True) else '') +
            ('' if S['id'] in {'fund', 'disagg', 'auto', 'adm'} else f'<div class="divnum">{k + 1:02d}</div>') +
            '</section>')
    return f'<div class="sec d-host" id="sec-host" inert><div class="hstage">{cover}{divs}</div></div>'


CHROME = """
<div class="dw-chrome">
  <div class="dw-left"><span class="dw-sec" id="dw-sec"></span><span class="dw-title" id="dw-title"></span></div>
  <div class="dw-right">
    <span class="dw-dots" id="dw-dots"></span>
    <button class="dw-btn" id="dw-prev" aria-label="Previous">◀</button>
    <span class="dw-pg" id="dw-pg"></span>
    <button class="dw-btn" id="dw-next" aria-label="Next">▶</button>
    <button class="dw-btn" id="dw-notes" aria-label="Toggle speaker notes" title="Speaker notes (N)">Notes</button>
    <button class="dw-btn" id="dw-theme" aria-label="Toggle dark mode" title="Dark / light (T)">Dark</button>
    <button class="dw-btn" id="dw-all" aria-label="All slides" title="All slides (O)">All slides</button>
    <button class="dw-btn" id="dw-fs" aria-label="Toggle fullscreen" title="Full screen (F)">⛶</button>
  </div>
</div>
<div class="dw-progress" id="dw-progress"></div>
<div class="dw-notes" id="dw-notespanel" aria-live="polite"><div class="dw-nh">Speaker notes<span id="dw-notes-title"></span><button class="dw-btn" id="dw-notes-close" style="height:28px;min-width:0;padding:0 10px;font-size:12px">Close</button></div><div id="dw-notes-body"></div></div>
<div class="dw-ov" id="dw-ov" role="dialog" aria-label="All slides"><div class="dw-ov-h"><b>All slides</b><span>click a slide · arrows + Enter · Esc to close</span><button class="dw-btn" id="dw-ov-close">Close</button></div><div class="dw-ov-g" id="dw-ov-grid"></div></div>
"""


def split_slides(markup):
    """Split a deck's markup into (prefix, [slide html...], suffix); slides are the <section class="slide"> elements."""
    starts = [m.start() for m in re.finditer(r'<section\b[^>]*class="[^"]*\bslide\b', markup)]
    prefix = markup[:starts[0]]
    slides = [markup[a:b] for a, b in zip(starts, starts[1:] + [len(markup)])]
    last = slides[-1]
    end = last.rfind('</section>') + len('</section>')
    slides[-1], suffix = last[:end], last[end:]
    return prefix, slides, suffix


def expand_program(built):
    """Resolve PROGRAM into one [(deck, index), ...] list per host section."""
    prog = []
    for S in PROGRAM:
        entries = []
        for deck, idxs in S['slides']:
            n = len(built[deck]['slides'])
            idxs = list(range(n)) if idxs == '*' else list(idxs)
            bad = [i for i in idxs if not 0 <= i < n]
            if bad:
                raise SystemExit(f'build: section {S["id"]}: deck {deck} has no slide {bad} (it has {n})')
            entries += [(deck, i) for i in idxs]
        prog.append(entries)
    return prog


def plain_text(h):
    return htmlmod.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', h))).strip()


def headline(slide):
    """What a Router slide is about, for the "Next →" teaser of the slide before it."""
    tag = re.match(r'<section\b[^>]*>', slide).group(0)
    classes = (re.search(r'class="([^"]*)"', tag) or [None, ''])[1].split()
    if 'hero' in classes:
        eb = re.search(r'<div class="eyebrow"[^>]*>(.*?)</div>', slide, flags=re.S)
        h1 = re.search(r'<h1[^>]*>(.*?)</h1>', slide, flags=re.S)
        return plain_text((eb.group(1) if eb else '') + ' · ' + (h1.group(1) if h1 else ''))
    h = re.search(r'<h2[^>]*>(.*?)</h2>', slide, flags=re.S) or re.search(r'<h1[^>]*>(.*?)</h1>', slide, flags=re.S)
    return plain_text(h.group(1)) if h else ''


def set_section_attr(slide, name, value):
    tag = re.match(r'<section\b[^>]*>', slide).group(0)
    new = re.sub(r'\s' + re.escape(name) + r'="[^"]*"', '', tag)
    if value is not None:
        new = '<section ' + f'{name}="{htmlmod.escape(value, quote=True)}"' + new[len('<section'):]
    return new + slide[len(tag):]


def router_teasers(slides, prog):
    """The Router deck shows a "Next →" teaser (data-next) per slide. Where the program changed what follows a slide,
    point the teaser at the slide that now follows, or drop it when the section ends."""
    succ = {}
    for entries in prog:
        for a, b in zip(entries, entries[1:] + [None]):
            if a[0] == 'router':
                succ[a[1]] = b[1] if (b and b[0] == 'router') else None
    for i, nxt in succ.items():
        if nxt == i + 1:
            continue
        slides[i] = set_section_attr(slides[i], 'data-next', None if nxt is None else headline(slides[nxt]))


def main():
    extra = load_module('session_admission')     # the new session-aware admission slides (Router deck conventions)
    built = {}
    for D in DECKS:
        sid = D['id']
        if D['family'] == 'N':
            css, markup, js = build_native(D)
        else:
            html = (SRC / D['file']).read_text(encoding='utf-8')
            if D['family'] == 'A':
                css, markup, js = build_family_a(D, html)
            elif sid == 'router':
                css, markup, js = build_router(D, html, extra_js=f'Object.assign(NOTES, {json.dumps(extra.NOTES)});',
                                               extra_css=extra.CSS)
            elif sid == 'ft':
                css, markup, js = build_ft(D, html)
            elif D['family'] == 'P':
                css, markup, js = build_planner(D, html)
            else:
                css, markup, js = build_mx(D, html)
        for fn in DECK_PATCHES.get(sid, []):
            markup = fn(markup)
        prefix, slides, suffix = split_slides(markup)
        if sid == 'router':
            slides += [drop_stray_closes(h, f'router extra slide {i}') for i, h in enumerate(extra.SLIDES)]
        for (d, i), fns in SLIDE_PATCHES.items():
            if d == sid:
                for fn in fns:
                    slides[i] = fn(slides[i])
        built[sid] = dict(css=css, prefix=prefix, slides=slides, suffix=suffix, js=js)

    load_module('content_edits').apply(built, PROGRAM)
    prog = expand_program(built)
    router_teasers(built['router']['slides'], prog)
    used = {sid: set() for sid in built}
    for entries in prog:
        for d, i in entries:
            used[d].add(i)

    css_parts, markup_parts, js_parts = [], [], []
    for D in DECKS:
        sid, B = D['id'], built[D['id']]
        slides = [h if i in used[sid] else re.sub(r'^<section\b', '<section data-dw-off=""', h, count=1)
                  for i, h in enumerate(B['slides'])]
        markup = fix_links(B['prefix'] + '\n'.join(slides) + B['suffix'])
        node_check(B['js'], sid)
        css_parts.append(f'/* ===================== section: {sid} ===================== */\n' + scope_css(B['css'], sid))
        markup_parts.append(f'<div class="sec d-{sid}" id="sec-{sid}" inert>\n{markup}\n</div>')
        js_parts.append(B['js'])

    sections_json = json.dumps([dict(id=S['id'], name=S['name'], desc=S['desc'], slides=[list(e) for e in entries])
                                for S, entries in zip(PROGRAM, prog)])
    host_js = HOST_JS.replace('__SECTIONS__', sections_json)
    node_check(host_js, 'host')

    page = f"""<!DOCTYPE html>
<html lang="en" class="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DSX OS AI Inference Workshop - Dynamo</title>
<meta name="description" content="NVIDIA Dynamo workshop deck: {', '.join(S['name'] for S in PROGRAM)}.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<script>{HEAD_THEME_JS}</script>
<style>
{HOST_CSS}
</style>
<style>
{chr(10).join(css_parts)}
</style>
</head>
<body>
<!--
  NVIDIA Dynamo workshop deck, generated by build/build.py. Section 1 is authored in build/fundamentals.py, the
  session-aware admission slides in build/session_admission.py; the other slides come from https://ai-dynamo.org/slides/
  Sections (in order): {', '.join(S['name'] for S in PROGRAM)}.
  The PROGRAM list in build.py decides which deck slides are shown, in which order; every source deck's slides stay in
  the DOM inside <div class="sec d-…" id="sec-…"> and the ones not in the program carry data-dw-off (never shown).
  Divider slides are in <div id="sec-host">.
  Keys: ← → step/slide · Shift+← → section · N notes · O all slides · T dark · F full screen.
-->
{host_markup()}
{chr(10).join(markup_parts)}
{CHROME}
<script>
{host_js}
</script>
<script>
{chr(10).join(js_parts)}
</script>
<script>DW.start();</script>
</body>
</html>
"""
    OUT.write_text(page, encoding='utf-8')
    total = sum(len(e) for e in prog)
    print(f'wrote {OUT} ({len(page) / 1024:.0f} KB)')
    for S, entries in zip(PROGRAM, prog):
        print(f'  {S["id"]:8s} {len(entries):3d} slides  ({", ".join(f"{d}:{i}" for d, i in entries)})')
    print(f'  total    {total:3d} slides + 1 cover + {len(PROGRAM)} dividers = {total + 1 + len(PROGRAM)}')
    hidden = {sid: len(B['slides']) - len(used[sid]) for sid, B in built.items()}
    print('  unused slides kept in the DOM: ' + ', '.join(f'{k} {v}' for k, v in hidden.items() if v))


if __name__ == '__main__':
    main()
