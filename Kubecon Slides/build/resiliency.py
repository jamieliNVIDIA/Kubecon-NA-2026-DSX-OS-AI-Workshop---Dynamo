"""Resiliency pieces authored for the Dynamo workshop deck (outline section 3): the section opener, the request-continuity demo
cues, the bridge from a surviving request to lost capacity, the Shadow Engine and DGD Snapshot demo cues, and the recap that
closes the Snapshot section. Same conventions and visual language as fundamentals.py, whose CSS and helpers are reused; built as
the 'resiliency' deck and placed by PROGRAM in build.py around slides of the ai-dynamo.org fault-tolerance and mx-snapshot decks.
"""
import html as htmlmod
import importlib.util
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('fundamentals', HERE / 'fundamentals.py')
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)
slide, kick, node, label, arrow, overlay, card, esc, MARKERS = F.slide, F.kick, F.node, F.label, F.arrow, F.overlay, F.card, F.esc, F.MARKERS
JS = F.JS

# The Shadow demo runs a different model from the rest of the workshop: Super VL is blocked on GMS integration bugs. The October 22
# control that passed used Qwen3-0.6B at TP1. Change this when the demo is qualified on another model; slides 5 and 6 use it.
SHADOW_DEMO_MODEL = 'Qwen3-0.6B'

CSS = F.CSS + r"""
/* ===== opener: three questions ===== */
.qs{position:absolute;display:flex;flex-direction:column;gap:18px;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:18px;box-shadow:var(--dw-shadow);padding:24px 30px}
.qs h4{font:600 16px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--dw-green-ink)}
.qs p{display:flex;align-items:flex-start;font:700 24px/1.25 Inter,sans-serif}
.qs p small{display:block;font:500 19px/1.3 Inter,sans-serif;color:var(--dw-dim);margin-top:4px}
.span2{position:absolute;display:flex;align-items:center;gap:18px;background:var(--f-amber-soft);border:2px dashed var(--f-amber-line);border-radius:16px;padding:16px 24px;font-size:21px;line-height:1.35;color:var(--dw-text)}
.span2 .tag{flex:none;align-self:center;color:var(--f-amber);background:var(--dw-surface)}
/* ===== demo cues ===== */
.demo.c4{grid-template-columns:repeat(4,1fr)}
.demo.c4 .card .chip{font-size:15px;padding:8px 12px}
/* ===== capacity after a crash: workers serving over time ===== */
.cg{position:absolute;left:0;top:0;width:1680px;height:240px;overflow:visible}
.cg text{font:500 18px Inter,sans-serif;fill:var(--dw-dim)}
.cg text.b{font:700 20px Inter,sans-serif;fill:var(--dw-text)}
.cg text.r{font:700 20px Inter,sans-serif;fill:var(--f-rose)}
.cg text.g{font:700 20px Inter,sans-serif;fill:var(--dw-green-ink)}
.cg .ax{stroke:var(--dw-line);stroke-width:3}
.cg .grid{stroke:var(--dw-line);stroke-width:1.5;stroke-dasharray:4 6}
.cg .gap{fill:var(--f-rose-soft)}
.cg .cap{fill:none;stroke:var(--dw-green-ink);stroke-width:6;stroke-linejoin:round}
.cg .kill{stroke:var(--f-rose);stroke-width:4}
/* ===== migration under load ===== */
.ld{position:absolute;left:0;width:1680px;display:grid;grid-template-columns:1fr 330px 330px;gap:24px;align-items:stretch}
.ld>div{background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:18px;box-shadow:var(--dw-shadow);padding:22px 28px;display:flex;flex-direction:column;justify-content:center;gap:8px}
.ld h3{font:700 27px/1.2 Inter,sans-serif}
.ld p{font-size:21px;line-height:1.4;color:var(--dw-dim)}
.ld b{font:800 52px/1 Inter,sans-serif;letter-spacing:-.02em}
.ld .off b{color:var(--f-rose)}.ld .on b{color:var(--dw-green-ink)}
.ld small{font:500 18px/1.3 "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
/* ===== recap: one row per failure ===== */
.rc{position:absolute;left:0;top:0;width:1680px;display:flex;flex-direction:column;gap:12px}
.rc .r{display:grid;grid-template-columns:360px 300px 180px 1fr;align-items:center;gap:24px;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:14px;padding:16px 24px;box-shadow:var(--dw-shadow)}
.rc .r.hd{background:transparent;border-color:transparent;box-shadow:none;padding-top:0;padding-bottom:0;margin:0;font:600 15px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--dw-dim)}
.rc .f{font:700 25px/1.2 Inter,sans-serif}
.rc .m{font:600 23px/1.25 Inter,sans-serif;color:var(--dw-text)}
.rc .mat{justify-self:start;font:600 14px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--dw-dim);border:1px solid var(--dw-line);border-radius:999px;padding:7px 12px}
.rc .ev{display:flex;align-items:center;gap:14px;font-size:21px;line-height:1.3;color:var(--dw-dim)}
.rc .ev i{flex:none;width:116px;text-align:center;font:700 14px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;font-style:normal;letter-spacing:.1em;text-transform:uppercase;padding:7px 0;border-radius:999px}
.rc .ev i.live{color:var(--dw-green-ink);background:var(--f-green-soft)}
.rc .ev i.test{color:var(--dw-cyan);background:var(--f-cyan-soft)}
.rc .ev i.bench{color:var(--f-amber);background:var(--f-amber-soft)}
.rc .ev i.none{color:var(--dw-dim);background:var(--f-dim-soft)}
.rc .ev i.vis{color:var(--f-rose);background:var(--f-rose-soft)}
"""


def steps_note(items):
    return '<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'


def demo_cards(steps):
    return ''.join(f'<div class="card"><span class="num">{n}</span><div><h3>{h}</h3><p>{p}</p><span class="chip">{esc(c)}</span></div></div>'
                   for n, h, p, c in steps)


def code_line(text, note='', col=0):
    """One line of a .code block; a note becomes a comment starting at column `col` of the visible text."""
    if note:
        pad = max(col - len(htmlmod.unescape(re.sub(r'<[^>]+>', '', text))), 2)
        text += ' ' * pad + f'<span class="c"># {note}</span>'
    return f'<span class="ln">{text}</span>'


# ----------------------------------------------------------------------------- section opener
def r1_questions():
    body = MARKERS + overlay(
        arrow(242, 155, 306, 155),
        arrow(632, 120, 716, 66, mid=(670, 66)),
        arrow(632, 190, 716, 226, mid=(670, 226)))
    body += node(0, 70, 240, 170, '<h3><small>client</small>Agent</h3><p>Streams a coding answer</p>')
    body += node(310, 40, 320, 230, '<h3><small>no GPU</small>Frontend</h3>'
                                    '<p>Routes each request and keeps its generated tokens for <b>migration</b>.</p>', cls='g')
    body += node(720, 0, 320, 130, '<h3><small>TP2 · 2 &#215; H100</small>Worker 1</h3>', cls='c')
    body += node(720, 160, 320, 130, '<h3><small>TP2 · 2 &#215; H100</small>Worker 2</h3>', cls='c')
    body += ('<div class="qs" style="left:1110px;top:0;width:570px" data-s="1"><h4>Ask of every failure</h4>'
             '<p><span class="num">1</span><span>Do the affected requests complete?<small>or does the agent get an error</small></span></p>'
             '<p><span class="num">2</span><span>When does usable capacity come back?<small>serving traffic, not just Ready</small></span></p>'
             '<p><span class="num">3</span><span>What happens to latency meanwhile?<small>TTFT and per-user speed on the survivors</small></span></p>'
             '</div>')
    body += ('<div class="cards c3" style="position:absolute;left:0;top:330px;width:1680px">'
             + card('g', 'A request is cut off',
                    '<p>Whatever fails, answers in flight stop part-way. <b>Request migration</b> finishes them on another worker; a '
                    'planned restart <b>drains</b> first.</p>', tag='any fault', s=2)
             + card('c', 'Software faults',
                    '<p>The engine process crashes or hangs; the GPU is fine. <b>GMS</b> keeps the weights in GPU memory and a parked '
                    '<b>Shadow Engine</b> takes over in seconds.</p>', tag='this section', s=3)
             + card('r', 'Hardware faults',
                    '<p>A failed GPU takes its Pod down; <b>Snapshot</b> restores the engine from the node&#8217;s local disk (live '
                    'demo). A lost node takes that disk too (slides only).</p>', tag='next section', s=3)
             + '</div>')
    body += ('<div class="span2" style="left:568px;top:615px;width:1112px" data-s="4"><span class="tag">KVCR-Guard</span>'
             '<span>Keeps the KV cache in host memory, outside the engine: it outlives a crashed engine or a failed GPU, but not a '
             'lost node.</span></div>')
    return slide(
        'Three questions for every failure',
        kick('3', 'Resiliency'),
        'Three questions for every failure',
        body, steps=4,
        foot='Back to aggregated serving for this section: one frontend, and workers that run both prefill and decode.',
        notes=(
            '<p>Opens the section with the outline&#8217;s three questions; ask them of every mechanism that follows, and keep completion, '
            'capacity and latency on the same timeline.</p>'
            + steps_note([
                'Topology change, stated out loud: we leave disaggregation behind. Two aggregated TP2 workers behind one frontend, so a '
                'failure has one place to happen.',
                'A request is cut off whatever the fault, so request migration comes first. A planned restart drains instead.',
                'Software faults (this section): the engine process crashes or hangs while its GPU stays healthy. GMS keeps the weights and a parked '
                'Shadow Engine takes over. Shadow covers process faults only, not GPUs or nodes.',
                'Hardware faults (the next section): a failed GPU takes its Pod down, and Snapshot restores an initialized engine into '
                'the replacement Pod. The live demo deletes the worker Pod to stand in for the failed GPU. A lost node is slides only: '
                'cross-node restore is not qualified on our cluster.',
                'KVCR-Guard spans both: its pool is host shared memory owned by a sidecar, so by design it outlives a crashed engine or a '
                'failed GPU, but not the node. We tested the crashed-engine case. Its slides come right after Shadow, on the way to '
                'Snapshot.'])
            + '<p class="dw-dim">About 1.5 minutes. Replaces the upstream &#8220;Every hop in the request path can fail&#8221; map, whose '
              'diagram is disaggregated and lists eight mechanisms the section does not cover.</p>'))


# ----------------------------------------------------------------------------- 3.1 request continuity
def r2_demo_off():
    body = MARKERS + overlay(
        arrow(382, 95, 556, 55, cls='g thick', head='fund-ah-g', mid=(470, 55)),
        arrow(382, 160, 556, 195, cls='dash', mid=(470, 195)))
    body += node(0, 30, 380, 190, '<h3><small>case 1 · migration off</small>Frontend</h3><span class="chip">DYN_MIGRATION_LIMIT=0</span>', cls='g')
    body += node(560, 0, 470, 110, '<h3><small>serving this stream</small>Worker A · TP2</h3>', cls='c')
    body += node(560, 140, 470, 110, '<h3><small>idle peer, model loaded</small>Worker B · TP2</h3>')
    body += ('<div class="banner" style="left:1080px;top:0;width:600px;height:250px">'
             '<span><b>Watch how the stream ends.</b><small>The HTTP status says 200 whether or not the answer finished.</small></span></div>')
    steps = [
        ('1', 'Two cases, one difference', 'Each case: a frontend and two TP2 workers. Only the migration limit differs: <b>0</b> now, '
                                           '<b>3</b> after the next slide.', 'DYN_MIGRATION_LIMIT=0'),
        ('2', 'Stream a coding answer', 'One request with no worker pin. The stream&#8217;s metadata names the worker serving it.',
         'POST /v1/chat/completions'),
        ('3', 'Kill its engine', 'After 16 chunks of visible output, <b>SIGKILL</b> that worker&#8217;s EngineCore. Its Pod and Worker B '
                                 'stay up.', 'kill -KILL <EngineCore pid>'),
        ('4', 'Read the ending', 'An error frame, then <b>[DONE]</b>, and no finish_reason. The answer stops part-way.', 'data: [DONE]'),
    ]
    body += f'<div class="demo c4" style="position:absolute;left:0;top:290px;width:1680px">{demo_cards(steps)}</div>'
    return slide(
        'Demo: break a streaming answer',
        kick('3.1', 'Demo'),
        'Demo: kill the engine mid-answer',
        body,
        sub='Migration off first. The same request and the same fault come back with migration on, after the next slide.',
        foot='Super VL TP2, eager profile, as in section 1. Both cases are primed offstage; nothing starts on stage.',
        notes=(
            '<p>Presenter implementation: the request-continuity terminal demo (<code>uv run python -m demos request-continuity</code>), '
            'after <code>request-continuity prepare --auto</code> and <code>prime --auto</code> offstage. Priming loads both cases '
            '(eight H100s) and takes about 25 minutes on EFS, so start it before the session.</p>'
            '<p><b>Choreography.</b> Step 1 lists the two DGDs, one per case, and diffs them: only the name and '
            '<code>DYN_MIGRATION_LIMIT</code> (0 versus 3) differ. Step 2 runs case 1. Come back to the slides for the mechanism, then '
            'return to the terminal for step 3, case 2.</p>'
            '<p><b>What to point at</b> (November 9 recording): the killed worker produced a service-unavailable error frame 2.6 s in, '
            'after 17 tokens, then <code>[DONE]</code>, and no successful finish. The status code was 200; only the frame says the '
            'answer failed. The frontend and Worker B kept running.</p>'
            '<p class="dw-dim">Fallback: demos/transcripts/live/05-request-continuity/20261109-a1/main.txt, the three-step flow. The kill '
            'is PID- and '
            'start-time-guarded inside the worker container, after 16 nonempty content chunks; the request has no worker pin, no '
            'guided decoding and one choice.</p>'))


def r3_demo_on():
    body = ('<div class="cards c2" style="position:absolute;left:0;top:0;width:1680px">'
            + card('r', 'Migration off',
                   '<p>Cut off part-way: an error frame, then <b>[DONE]</b>, and no finish_reason. The agent has half an answer and an '
                   'error to handle.</p>', tag='case 1')
            + card('g', 'Migration on',
                   '<p>Same response ID. <b>31 tokens</b> carried over to Worker B, which finished the answer with <b>stop</b>. The longest '
                   'pause between chunks was half a second.</p>', tag='case 2', s=1)
            + '</div>')
    body += ('<div class="ld" style="top:260px" data-s="2">'
             '<div><h3>Under load: four coding streams at once, one engine killed</h3>'
             '<p>Every stream completed before the fault, in both cases.</p></div>'
             '<div class="off"><small>migration off</small><b>2 / 4</b><small>streams completed</small></div>'
             '<div class="on"><small>migration on</small><b>4 / 4</b><small>kept 32 tokens each</small></div>'
             '</div>')
    body += ('<div class="banner" style="left:0;top:470px;width:1680px" data-s="3">'
             '<span><b>HTTP 200 hid both failures under load.</b> Only the error frames in the stream showed them.'
             '<small>Check how the stream ends, not the status code.</small></span></div>')
    return slide(
        'Demo: same fault, migration on',
        kick('3.1', 'Demo'),
        'Same fault, migration on: the answer finishes',
        body, steps=3,
        sub='Case 2 of the same demo: DYN_MIGRATION_LIMIT=3, an identical request, the same kill at the same point.',
        foot='Super VL TP2, eager profile, one run each: proof that streams finish, not a latency or SLO result. The exact handoff gap is '
             'not measured: the stream keeps naming the first worker.',
        notes=(
            '<p><b>Live demo, case 2</b> (November 4 run): the frontend trace shows the retry going to the peer and carrying 31 output '
            'tokens. The same response continued to <code>stop</code> and <code>[DONE]</code>, with no stream error and no restart of '
            'the frontend or Worker B. The longest gap between any two chunks of the whole response was 0.51 s; that is an upper bound '
            'on what the agent saw, not the handoff time.</p>'
            '<p><b>Why the trace, not the stream:</b> in the pinned runtime the worker field in the stream is written once, so it keeps '
            'naming Worker A. The frontend trace, matched by response ID, proves where the continuation ran.</p>'
            '<p><b>Under load</b> (November 5, recorded): four concurrent coding streams per case. Before the fault 4/4 completed in both '
            'cases. After one EngineCore kill: 2/4 with migration off, 4/4 with it on; each affected stream carried 32 tokens over. All '
            '16 stream captures were parsed and matched to their event journals. HTTP 200 alone did not reveal the two failed streams.</p>'
            '<p>Transition: the request survived. Next, the planned version of this failure (a rollout), then the capacity that is '
            'still missing.</p>'
            '<p class="dw-dim">Sources: reports/workshop-request-continuity-demo.md; '
            'demos/transcripts/live/05-request-continuity-load/README.md; reports/receipts/2026-11-05-migration-load.json. Not '
            'covered: AgentX replay, capacity recovery, SLO behavior, tool-call or JSON-schema requests (guided decoding is not '
            'migrated).</p>'))


# ----------------------------------------------------------------------------- 3.2 engine process recovery
def r4_capacity():
    T0, T1, READY = -60, 600, 493                     # seconds around the kill; READY: section 1's startup to Ready
    X0, X1, Y2, Y1, YA = 150, 1660, 64, 150, 196      # chart x range; y for two workers and one worker; the time axis
    X = lambda t: X0 + (t - T0) * (X1 - X0) / (T1 - T0)
    grid = ''.join(f'<line class="grid" x1="{X(t):.0f}" y1="{Y2 - 8}" x2="{X(t):.0f}" y2="{YA}"/>'
                   f'<text x="{X(t):.0f}" y="{YA + 30}" text-anchor="middle">{f"{t // 60} min" if t else "0"}</text>'
                   for t in range(0, T1 + 1, 120))
    chart = ('<svg class="cg" viewBox="0 0 1680 240" aria-hidden="true">'
             '<text x="0" y="22">workers serving</text>'
             f'<text class="b" x="{X0 - 24}" y="{Y2 + 7}" text-anchor="end">2</text>'
             f'<text class="b" x="{X0 - 24}" y="{Y1 + 7}" text-anchor="end">1</text>'
             f'{grid}<line class="ax" x1="{X0}" y1="{YA}" x2="{X1}" y2="{YA}"/>'
             f'<rect class="gap" x="{X(0):.0f}" y="{Y2}" width="{X(READY) - X(0):.0f}" height="{Y1 - Y2}"/>'
             f'<text class="b" x="{(X(0) + X(READY)) / 2:.0f}" y="{(Y2 + Y1) / 2 + 7:.0f}" text-anchor="middle">one worker carries all '
             'the traffic</text>'
             f'<path class="cap" d="M{X(T0):.0f} {Y2} H{X(0):.0f} V{Y1} H{X(READY):.0f} V{Y2} H{X(T1):.0f}"/>'
             f'<line class="kill" x1="{X(0):.0f}" y1="6" x2="{X(0):.0f}" y2="{YA}"/>'
             f'<text class="r" x="{X(0) + 12:.0f}" y="22">engine killed</text>'
             f'<text class="g" x="{X(0) + 12:.0f}" y="47">&#10003; request resumed 0.5 s later</text>'
             f'<text class="b" x="{X(READY) - 12:.0f}" y="47" text-anchor="end">restarted worker Ready · {READY} s</text>'
             '</svg>')
    cards = ('<div class="cards c3" style="position:absolute;left:0;top:270px;width:1680px">'
             + card('g', 'Did the request finish?',
                    '<p><b>Yes, within half a second.</b> Migration moved it to Worker B and the answer completed.</p>',
                    tag='question 1', s=1)
             + card('r', 'When is the capacity back?',
                    '<p><b>Minutes later.</b> The restarted worker loads its weights and initializes again: 493 s for a new worker in '
                    'section 1.</p>', tag='question 2', s=2)
             + card('a', 'What happens to latency?',
                    '<p><b>Everyone waits.</b> In a published two-worker example, p50 TTFT rose to 23.8 s and 201 of 399 requests waited '
                    'over 5 s for a first token.</p>', tag='question 3', s=3)
             + '</div>')
    return slide(
        'Capacity is still gone',
        kick('3.2', 'Engine process recovery'),
        'The request survived. The capacity didn&#8217;t.',
        chart + cards, steps=3,
        sub='One engine killed with migration on, checked against the three questions.',
        foot='Timeline and questions 1 and 2: our Super VL numbers (the migration demo, section 1&#8217;s startup). Question 3: '
             'NVIDIA&#8217;s two-worker GLM-5.2 example on B200, with a 283 s cold restart. Different setups; the shape is the point.',
        notes=(
            '<p>Bridge from 3.1 to 3.2, per the outline: the request survives, but how quickly does the capacity return? Keep '
            'completion, capacity and latency on one timeline, using the opener&#8217;s three questions.</p>'
            + steps_note([
                'Question 1, answered in the demo: migration resumed the stream on Worker B; the longest pause between chunks was '
                '0.51 s.',
                'Question 2: the killed worker comes back only after a full startup. Section 1 measured 493 s to Ready for a new Super VL '
                'worker (267 s of weight loading, 144 s of initialization). A container restarted in the same Pod skips scheduling and '
                'the image pull, but still loads and initializes: about 7 minutes. Until then Worker B carries everything.',
                'Question 3: we have no matched latency measurement of our own. NVIDIA&#8217;s published two-worker example (GLM-5.2 '
                'NVFP4, B200, TP8): with a 283 s cold restart, p50 TTFT after the fault was 23.8 s and 201 of 399 requests waited over '
                '5 s for a first token. The same numbers come back on the Shadow Engine slide, next to the fix.'])
            + '<p>Verbal cue for the next slide: capacity back in seconds needs the expensive parts (the weights, the initialization) '
              'ready before the failure.</p>'
            + '<p class="dw-dim">The capacity chart is schematic: two workers, then one from the kill until the restarted worker is '
              'Ready, drawn at 493 s. It is not a measured capacity trace.</p>'))


def r5_shadow_demo():
    code = (code_line('<span class="k">spec</span>:')
            + code_line('  <span class="k">components</span>:')
            + code_line('  - <span class="k">name</span>: worker')
            + code_line('    <span class="k">experimental</span>:')
            + code_line('      <span class="k">gpuMemoryService</span>: {<span class="k">deviceClassName</span>: …}', 'GMS owns the weights', 53)
            + code_line('      <span class="k">failover</span>: {}', 'active + parked shadow', 53)
            + code_line('    <span class="k">args</span>: [… <span class="v">--load-format gms --enable-sleep-mode</span>]')
            + code_line('  - <span class="k">name</span>: Frontend')
            + code_line('    <span class="k">env</span>: [{<span class="k">name</span>: DYN_MIGRATION_LIMIT, <span class="k">value</span>: '
                        '<span class="p">"0"</span>}]', 'fresh requests only', 53))
    body = f'<div class="code sm" style="position:absolute;left:0;top:0;width:1020px;height:280px">{code}</div>'
    body += ('<div class="banner" style="left:1060px;top:0;width:620px;height:280px">'
             '<span><b>One Pod, one GPU, two engines.</b> The shadow is initialized and parked, and holds no KV cache.'
             '<small>The clock runs from the kill command to the first verified response.</small></span></div>')
    steps = [
        ('1', 'One weight copy, two engines', 'The active and the shadow engine both map the weights that GMS holds, on the same '
                                              'GPU.', 'kubectl get pods'),
        ('2', 'Verify the parked standby', 'Failover state, GPU identity and the shared weight layout, checked before the fault.',
         'shadow: parked'),
        ('3', 'Lose the active engine', '<b>SIGKILL</b> its EngineCore. The shadow takes the lock, wakes and serves a fresh request.',
         'kill -KILL <EngineCore pid>'),
        ('4', 'Check restored capacity', 'A new worker identity, the same GMS, and a <b>new standby</b> parked behind it.',
         'standby replenished'),
    ]
    body += f'<div class="demo c4" style="position:absolute;left:0;top:320px;width:1680px">{demo_cards(steps)}</div>'
    return slide(
        'Demo: Shadow Engine failover',
        kick('3.2', 'Demo'),
        'Demo: kill the active engine, the shadow takes over',
        body,
        sub=f'A different model for this demo: <b>{SHADOW_DEMO_MODEL}</b> on one H100. Super VL still hits two GMS integration bugs.',
        foot='Fresh requests with migration off, so this measures capacity coming back, not in-flight requests. GMS and Shadow Engine are '
             'a preview.',
        notes=(
            f'<p>Presenter implementation: the Shadow terminal demo (<code>uv run python -m demos shadow</code>), after '
            f'<code>shadow prepare</code> and <code>shadow prime</code> offstage. New runs use {SHADOW_DEMO_MODEL} at TP1 on one H100 '
            f'(cp-0942 gpu-1). It passed its live qualification on November 8 (below). If the staged pair fails its morning check, '
            f'show the recording instead of the terminal.</p>'
            '<p><b>Why another model.</b> Super VL TP2 has never reached a fault: the GMS reader rejects '
            '<code>language_model.lm_head.input_scale</code> (parameter shape (1,) against committed shape ()), and the writer hits a CUDA '
            'illegal memory access during FlashInfer warm-up (October 22; the same family of failures in the November 4&#8211;5 '
            'retry). Say it plainly: a preview feature with model-specific integration gaps is a useful thing to know before adopting '
            'it.</p>'
            '<p><b>Evidence so far.</b> November 9, this presenter (Qwen3-0.6B at TP1 on cp-0942): the standby served the first '
            'verified response 1.2 s after the kill, in the same Pod and GMS, with a new worker identity and a new standby confirmed. '
            'One request failed during the switch. Fallback recording: <code>demos/transcripts/live/08-shadow-engine/20261109-a1</code>. '
            'November 8 took 1.7 s with two failed requests (1.2 s in an earlier run that night); the October 22 control took '
            '2.62 s.</p>'
            '<p class="dw-dim">Scope: process failures only, not GPU, Pod or node loss. The promoted engine starts with an empty KV '
            'cache, and in-flight requests need migration. Next: KVCR-Guard, for the cache.</p>'))


# ----------------------------------------------------------------------------- 3.3 Pod recovery: Snapshot demo cue
def r6_snapshot_demo():
    code = (code_line('<span class="k">spec</span>:')
            + code_line('  <span class="k">components</span>:')
            + code_line('  - <span class="k">name</span>: worker')
            + code_line('    <span class="k">experimental</span>:')
            + code_line('      <span class="k">checkpoint</span>:')
            + code_line('        <span class="k">enabled</span>: <span class="p">true</span>')
            + code_line('        <span class="k">startupPolicy</span>: <span class="v">WaitForCheckpoint</span>', 'Pods restore from the capture', 44)
            + code_line('        <span class="k">deletionPolicy</span>: <span class="v">Retain</span>', 'keep the checkpoint', 44))
    body = f'<div class="code sm" style="position:absolute;left:0;top:0;width:1680px;height:250px">{code}</div>'
    steps = [
        ('1', 'A worker, saved once', 'The DGD&#8217;s checkpoint settings. Capture and staging to local NVMe happened offstage.',
         'experimental.checkpoint'),
        ('2', 'Replace the worker Pod', 'Delete only the worker. The operator restores its replacement while the frontend stays put.',
         'kubectl delete pod <worker>'),
        ('3', 'Check what recovered', 'A new Pod and worker; the same DGD, frontend, checkpoint, node and GPU pair.', 'new Pod UID'),
        ('4', 'Use the recovered service', 'A fresh coding request through the unchanged frontend.', 'POST /v1/chat/completions'),
    ]
    body += f'<div class="demo c4" style="position:absolute;left:0;top:290px;width:1680px">{demo_cards(steps)}</div>'
    return slide(
        'Demo: replace the worker Pod',
        kick('3.3', 'Demo'),
        'Demo: delete the worker Pod, Snapshot brings it back',
        body,
        sub='A GPU failure the node survives: the replacement Pod restores from the checkpoint on node-local disk.',
        foot='Restores the initialized engine, not the failed stream or its KV cache. Super VL TP2 with the compiled profile and 8k '
             'context: not section 1&#8217;s eager demo. Cross-node restore is not qualified here.',
        notes=(
            '<p>Presenter implementation: the DGD Snapshot terminal demo (<code>uv run python -m demos snapshot-dgd</code>), after '
            '<code>snapshot-dgd prepare</code> and <code>prime --auto --timeout 5400</code> offstage. The November 5 prime took 45 '
            'minutes: it creates the DGD, captures the initialized engine, stages and hash-checks a node-local copy, then restores the '
            'first worker and checks a coding request. Keep that DGD alive: its checkpoint belongs to its UID.</p>'
            '<p><b>Framing:</b> this is the hardware-fault case from the section opener. A failed GPU takes its worker Pod down; as long '
            'as the node survives, the replacement restores from the checkpoint on its local disk. On stage, deleting the Pod stands in '
            'for the failure. A lost node takes the local checkpoint with it, which is the shared-storage case: slides only.</p>'
            '<p class="dw-dim">If asked: the replacement here lands on the same GPU pair it was captured on; we have not run a restore '
            'onto a different GPU of the node.</p>'
            '<p><b>On stage:</b> show the checkpoint settings, delete the worker Pod (UID-guarded), watch the operator restore its '
            'replacement, check the identity table, then send a fresh coding request through the same frontend. The readiness wait '
            'sends no inference, so presenter pauses stay outside the clocks.</p>'
            '<p><b>November 9 recording</b> (cp-0124): agent restore 35.1 s (CRIU 19.4 s, CUDA 14.1 s), Pod-to-Ready 60 s, '
            'deletion-to-observed-Ready 63.3 s, then a correct coding response. November 5 measured 33.9 s, 59 s and 64.3 s. Separate '
            'boundaries, not a matched speedup against a cold start.</p>'
            '<p class="dw-dim">Fallback: demos/transcripts/live/04-snapshot-dgd/20261109-a1/main.txt. The pinned runtime '
            'still carries the destination identity/offline bridge overlay (reports/2026-11-04-snapshot-upstream-status.md). Any '
            'hardware, runtime or placement change needs requalification. The checkpoint released the KV cache before capture, so a '
            'restored worker starts with an empty cache.</p>'))


# ----------------------------------------------------------------------------- 3.3 recap, closing the Snapshot section
RECAP = [  # failure (the opener's three kinds, plus startup and composition), what handles it, maturity, evidence class, badge, what we showed
    ('Any fault, mid-answer', 'Request migration', 'opt-in', 'live', 'live',
     'Super VL: streams finish on the peer, 4 of 4 under load'),
    ('Engine crash or hang', 'GMS + Shadow Engine', 'preview', 'live', 'live',
     f'{SHADOW_DEMO_MODEL}. Super VL is blocked on GMS bugs'),
    ('Crash or failed GPU', 'KVCR-Guard', 'in development', 'test', 'tested',
     'Super VL, engine killed: 4,224 tokens reused'),
    ('A failed GPU', 'Snapshot, local disk', 'experimental', 'live', 'live',
     'Super VL: Pod replaced, restored from local NVMe'),
    ('A lost node', 'Snapshot, shared storage', 'experimental', 'none', 'not shown',
     'Diagram only: cross-node restore not qualified here'),
    ('Any new replica', 'ModelExpress + Snapshot', 'experimental', 'bench', 'benchmark',
     'Internal: Qwen3-Next-80B on one B200, 180 s to 14 s'),
    ('Several at once', 'The full stack together', '&#8212;', 'vis', 'vision',
     'Each piece works alone; not tested together'),
]


def r7_recap():
    rows = ('<div class="r hd"><span>Failure</span><span>What handles it</span><span>Status</span><span>What we showed</span></div>'
            + ''.join(f'<div class="r"><span class="f">{f}</span><span class="m">{m}</span><span class="mat">{st}</span>'
                      f'<span class="ev"><i class="{c}">{b}</i><span>{e}</span></span></div>'
                      for f, m, st, c, b, e in RECAP))
    return slide(
        'Which layer handles which failure',
        kick('3.3', 'Putting it together'),
        'What handles each failure, and what we showed',
        f'<div class="rc">{rows}</div>',
        foot='Every line was qualified on its own configuration. A working piece does not make the combination supported, and none '
             'of these is labelled production-ready.',
        notes=(
            '<p>The outline&#8217;s &#8220;return to the combined recovery story&#8221;: the section opener&#8217;s three kinds of '
            'failure, now with the evidence behind each. Migration continues requests; GMS and Shadow restore capacity after software '
            'faults; KVCR-Guard keeps cached context through an engine crash (and, by design, a failed GPU); Snapshot restores an '
            'initialized replacement Pod after a GPU failure the node survives; ModelExpress, from scaling, is the weight-loading '
            'path.</p>'
            + steps_note([
                '<b>Live</b>: run on stage on our cluster. <b>Tested</b>: run on our cluster, not on stage. <b>Benchmark</b>: someone '
                'else&#8217;s measurement, labelled with its setup. <b>Vision</b>: a direction, not a tested composition.',
                'KVCR-Guard (November 4, nightly runtime): with one engine down, a request pinned to the peer pulled 6 blocks (99 MiB) '
                'from the Guard and reused 4,224 prompt tokens; the restarted engine then reused them locally. The first unpinned '
                'request failed with a 503, so automatic failover is not qualified. The live KVCR demo has Guard installed but '
                'injects no failure: it is not Guard evidence.',
                'Readiness, as the outline asks: Shadow Engine is a preview, the Snapshot project cautions against production-critical '
                'use, and KVCR-Guard is in development. Composition (for example, Snapshot shortening standby replenishment) is '
                'vision until it is tested.'])))


SLIDES = [r1_questions, r2_demo_off, r3_demo_on, r4_capacity, r5_shadow_demo, r6_snapshot_demo, r7_recap]


def render_slides():
    return [f() for f in SLIDES]


if __name__ == '__main__':
    for i, h in enumerate(render_slides()):
        print(i, len(h))
