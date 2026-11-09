"""Section 2 pieces authored for the Dynamo workshop deck: the scaling opener (outline 2.1), disaggregation (2.5) and
a short introduction to the Planner (2.6). Same conventions and visual language as fundamentals.py, whose CSS and
helpers are reused; built as the 'scaling' deck and split across host sections by PROGRAM in build.py.
"""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('fundamentals', HERE / 'fundamentals.py')
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)
slide, kick, node, label, arrow, overlay, card, esc, MARKERS = F.slide, F.kick, F.node, F.label, F.arrow, F.overlay, F.card, F.esc, F.MARKERS
JS = F.JS

CSS = F.CSS + r"""
/* ===== scaling opener ===== */
.ag{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px}
.ag span,.rq span{display:flex;align-items:center;gap:10px;height:46px;border-radius:12px;padding:0 16px;font:600 19px/1 Inter,sans-serif;border:1px solid var(--dw-line);background:var(--f-dim-soft);color:var(--dw-text);white-space:nowrap;min-width:0}
.ag span small,.rq span small{font:500 15px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);margin-left:auto;overflow:hidden;text-overflow:ellipsis}
.ag span.go{background:var(--f-green-soft);border-color:var(--f-green-line)}
.ag span.tool{background:var(--f-amber-soft);border-color:var(--f-amber-line);border-style:dashed}
.ag span.sub{background:var(--f-cyan-soft);border-color:var(--f-cyan-line)}
.rq{display:flex;flex-direction:column;gap:10px;margin-top:4px}
.rq span.act{background:var(--f-cyan-soft);border-color:var(--f-cyan-line)}
.rq span.q{background:transparent;border:2px dashed var(--dw-line);color:var(--dw-dim)}
.cnt{display:flex;gap:14px;margin-top:auto;padding-top:10px}
.cnt b{font:700 30px/1 Inter,sans-serif;letter-spacing:-.02em}.cnt small{display:block;font:500 15px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);margin-top:6px}
.chart{position:absolute;left:0;top:0;width:1100px;height:560px}
.chart text{font:500 19px Inter,sans-serif;fill:var(--dw-dim)}
.chart .ax{stroke:var(--dw-line);stroke-width:4;fill:none}
.chart .tk{stroke:var(--dw-line);stroke-width:2}
.chart .cv{fill:none;stroke-width:7;stroke-linecap:round}
.chart .cv.g{stroke:var(--dw-green-ink)}.chart .cv.c{stroke:var(--dw-cyan)}.chart .cv.a{stroke:var(--f-amber)}
.chart .zone{fill:var(--f-rose-soft)}
.chart .tgt{stroke:var(--dw-cyan);stroke-width:3;stroke-dasharray:12 12;fill:none}
.chart .dot{fill:var(--f-rose);stroke:var(--dw-surface);stroke-width:4}
.chart text.g{fill:var(--dw-green-ink);font-weight:600}.chart text.c{fill:var(--dw-cyan);font-weight:600}.chart text.a{fill:var(--f-amber);font-weight:600}.chart text.r{fill:var(--f-rose);font-weight:700}
.side{position:absolute;left:1140px;top:0;width:540px;display:flex;flex-direction:column;gap:14px}
.side .card{padding:18px 24px 20px;gap:6px}
.side .card h3{font-size:24px}.side .card p{font-size:19px;line-height:1.38}
.mem.host .m{justify-content:flex-start;padding-top:14px}
.pool i[data-only]{display:none}.pool i[data-only].on{display:flex}
.pool i.cold{background:var(--f-dim-soft);color:var(--dw-dim);border:1px solid var(--dw-line)}
.pool i.evict{background:var(--f-rose-soft);color:var(--f-rose);border:1px solid var(--f-rose-line)}
/* ===== disaggregation ===== */
.ov text{font:600 19px Inter,sans-serif;fill:var(--dw-text)}
.ov text.d{fill:var(--dw-dim);font-weight:500}
.ov text.r{fill:var(--f-rose)}
.ov path.r{stroke:var(--f-rose);stroke-width:3}
.ov rect.dec{fill:var(--dw-cyan)}
.ov rect.pre{fill:var(--dw-green-fill)}
.kt{border-collapse:collapse;font-size:20px;line-height:1.3;margin:4px 0}
.kt td{padding:4px 14px 4px 0;color:var(--dw-dim)}.kt td b{color:var(--dw-text);font-weight:700}
.dm{display:grid;grid-template-columns:230px 1fr 190px;gap:18px;align-items:center;font-size:21px;line-height:1.25;color:var(--dw-dim)}
.dm b{color:var(--dw-text);font-weight:600}
.dm i{height:16px;border-radius:8px;background:var(--f-dim-soft);position:relative;overflow:hidden}
.dm i b{position:absolute;left:0;top:0;bottom:0;border-radius:8px;background:var(--dw-green-fill)}
.card.c .dm i b{background:var(--dw-cyan)}
.dm small{font:500 17px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.dms{display:flex;flex-direction:column;gap:16px;margin-top:8px}
.wk{position:absolute;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:16px;box-shadow:var(--dw-shadow);padding:16px 22px;display:flex;flex-direction:column;gap:6px;transition:border-color .3s}
.wk h4{font:700 24px/1.1 Inter,sans-serif}.wk small{font:500 16px/1.3 "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.wk.g{border-top:6px solid var(--dw-green-fill)}.wk.c{border-top:6px solid var(--dw-cyan)}
.wk.ghost{background:transparent;border:2px dashed var(--dw-line);box-shadow:none;color:var(--dw-dim);justify-content:center;align-items:center}
.wk.ghost h4{color:var(--dw-dim);font-weight:600}
.gpu{display:flex;gap:6px;margin-top:4px}.gpu i{width:36px;height:14px;border-radius:4px;background:var(--f-dim-soft);border:1px solid var(--dw-line)}
.wk.g .gpu i{background:var(--f-green-soft)}.wk.c .gpu i{background:var(--f-cyan-soft)}
"""


def steps_note(items):
    return '<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'


# ----------------------------------------------------------------------------- 2.1 scaling opener
def c1_agents():
    agents = ''.join([
        '<span class="go">A1<small>request in flight</small></span>',
        '<span class="tool">A2<small>waiting on a tool</small></span>',
        '<span class="tool">A3<small>waiting on a tool</small></span>',
        '<span class="go">A4<small>request in flight</small></span>',
        '<span class="go">A5<small>request in flight</small></span>',
        '<span class="tool">A6<small>waiting on a tool</small></span>',
        '<span class="go">A7<small>request in flight</small></span>',
        '<span class="sub">A8<small>3 subagents</small></span>',
    ])
    left = node(0, 20, 540, 540,
                '<h3>Coding agents<small>what AIPerf turns up</small></h3>'
                '<p>Eight sessions. Some are generating, some are waiting for a tool to finish, one has fanned out into three subagents.</p>'
                f'<div class="ag">{agents}</div>'
                '<div class="cnt"><div><b>8</b><small>agents</small></div><div style="margin-left:40px"><b>7</b><small>requests in flight</small></div></div>',
                'g', 1)
    queued = ('<span class="q">A8 · subagent 3<small>waiting</small></span>'
              '<span class="q">A7 · turn 12<small>waiting</small></span>')
    mid = node(640, 20, 400, 540,
               '<h3>Frontend<small>router and queue</small></h3>'
               '<p>Requests the engine can&#8217;t take yet wait here, or in the engine&#8217;s own scheduler queue.</p>'
               f'<div class="rq">{queued}</div>'
               '<div class="cnt"><div><b>2</b><small>waiting</small></div></div>',
               '', 2)
    active = ''.join(f'<span class="act">{a}<small>{w}</small></span>' for a, w in [
        ('A1 · turn 4', 'decode'), ('A4 · turn 9', 'decode'), ('A5 · turn 2', 'prefill'),
        ('A8 · subagent 1', 'decode'), ('A8 · subagent 2', 'prefill')])
    right = node(1140, 20, 540, 540,
                 '<h3>Engine<small>one replica, one batch</small></h3>'
                 '<p>Everything in this list is in the current batch and shares the KV pool.</p>'
                 f'<div class="rq">{active}</div>'
                 '<div class="cnt"><div><b>5</b><small>running</small></div></div>',
                 'c', 3)
    banner = ('<div class="banner" style="left:0;top:585px;width:1680px;height:140px" data-s="4">'
              '<span>8 agents, 7 requests in flight, 5 running and 2 waiting. AIPerf turns up the first number; the engine only ever feels the other two.'
              '<small>Tool calls and subagents are why the numbers drift apart, and a coding-agent workload has plenty of both.</small></span></div>')
    arrows = overlay(arrow(540, 255, 640, 255, '', 2), arrow(1040, 255, 1140, 255, '', 3))
    return slide(
        'Same workload, more agents',
        kick('1.6', 'Scaling: more traffic, same workload'),
        'Turn up the load and watch three numbers',
        MARKERS + left + mid + right + banner + arrows, steps=4,
        foot='AIPerf raises the offered load. We only change the deployment: the replica count now, the serving layout later. '
             'The workload itself stays fixed all day.',
        notes=(
            '<p>Keep the coding-agent workload and increase concurrency with AIPerf (or show a measured curve). AIPerf changes offered load; '
            'the presenter changes the deployment&#8217;s desired replica count.</p>'
            + steps_note([
                'Concurrent agents, active engine requests and queued requests are different quantities. An agent waiting on a tool has no '
                'request in flight; an agent that forked three subagents has three.',
                'One engine batches work from many requests, including requests from different users; how many it can keep active is bounded '
                'by scheduling limits and KV-cache capacity.',
                'The numbers on the slide are a made-up snapshot, not a measurement.'])))


def c2_curve():
    xs = {1: 90, 4: 367, 16: 644, 64: 921, 128: 1060}
    ticks = ''.join(f'<line class="tk" x1="{x}" y1="470" x2="{x}" y2="482"/><text x="{x}" y="508" text-anchor="middle">{c}</text>' for c, x in xs.items())
    chart = (
        '<svg class="chart" viewBox="0 0 1100 560" aria-hidden="true">'
        '<rect class="zone" x="760" y="40" width="300" height="430" rx="14" data-s="4"/>'
        '<text class="r" x="910" y="70" text-anchor="middle" data-s="4">where it stops</text>'
        '<text x="910" y="96" text-anchor="middle" data-s="4" style="font-size:16px">queueing · KV pressure · preemption</text>'
        '<path class="ax" d="M90 40 L90 470 L1060 470"/>'
        f'{ticks}'
        '<text x="575" y="545" text-anchor="middle">requests running at once on one replica (illustrative scale)</text>'
        '<text x="60" y="256" text-anchor="middle" transform="rotate(-90 60 256)">higher →</text>'
        '<path class="cv g" d="M90 440 C 250 420, 300 160, 520 130 S 900 115, 1060 125" data-s="1"/>'
        '<text class="g" x="560" y="104" text-anchor="middle" data-s="1">output tokens/s per GPU</text>'
        '<path class="cv c" d="M90 110 C 300 112, 420 150, 600 250 S 900 390, 1060 410" data-s="2"/>'
        '<text class="c" x="1050" y="450" text-anchor="end" data-s="2">output tokens/s per user</text>'
        '<path class="cv a" d="M90 452 L 640 446 C 780 440, 880 360, 1060 230" data-s="3"/>'
        '<text class="a" x="1040" y="212" text-anchor="end" data-s="3">time to first token</text>'
        '<line class="tgt" x1="90" y1="300" x2="1060" y2="300" data-s="5"/>'
        '<text class="c" x="100" y="290" data-s="5">the per-user speed we promised</text>'
        '<circle class="dot" cx="700" cy="300" r="13" data-s="5"/>'
        '<text class="r" x="640" y="340" text-anchor="end" data-s="5">below the line: add capacity →</text>'
        '</svg>')
    side = ('<div class="side">'
            + card('g', 'Throughput climbs', '<p>More requests share every forward pass, so the GPU produces more tokens per second in total, until it saturates.</p>', s=1)
            + card('c', 'Per-user speed drops', '<p>Each user gets a smaller slice of every step. Measure this over the time a user is actually generating.</p>', s=2)
            + card('a', 'Then TTFT climbs', '<p>Time to first token barely moves until requests start waiting for a slot, then it grows quickly.</p>', s=3)
            + card('r', 'Where it stops', '<p>Scheduler limits and KV capacity overlap. Run out of KV and the engine preempts requests and recomputes them. Don&#8217;t expect a smooth curve.</p>', s=4)
            + '</div>')
    cap = ('<div class="alabel l" style="left:0;top:585px;width:1100px;font-size:19px;font-weight:500;color:var(--dw-dim)">'
           'Shape only, not data. The real sweep at C16 to C128 on one and two workers is still running; C1 and C4 were single load points.</div>')
    return slide(
        'Throughput versus interactivity',
        kick('1.6', 'Scaling: more traffic, same workload'),
        'More throughput, less speed per user',
        chart + side + cap, steps=5,
        foot='Two goals pull against each other: tokens per second per GPU is what the service costs, tokens per second per user is how it feels. '
             'You can&#8217;t get the second by dividing the first by the number of agents.',
        notes=(
            '<p>Explain the useful concurrency regime before showing its limits.</p>'
            + steps_note([
                'GPU parallelism and engine batching let many requests share the GPU efficiently; as concurrency rises, aggregate throughput '
                'can increase while generation speed per user decreases. The service completes more work overall while becoming less '
                'interactive for each user.',
                'The regime has limits: scheduling and memory constraints can leave requests waiting, and insufficient KV-cache capacity can '
                'cause preemption and recomputation. Do not promise a smooth curve or that queuing begins only when KV cache fills.',
                'When the observed experience falls below the target, add serving capacity (next slides).',
                'Output tokens/s per GPU is resource efficiency; output tokens/s per user, over a clearly defined active generation window, is '
                'interactivity. Agents wait on tools, fork subagents and sit in queues, so never divide one by the session count to get the other.'])
            + '<p class="dw-dim">The curve and load levels remain measurements to collect (load-sweep status report). Keep agent concurrency, '
            'active inference requests and queued requests distinguishable on any real plot.</p>'))


def c3_limits():
    pool_full = ('<div class="pool" data-s="1">'
                 '<i style="width:100px">A1</i><i style="width:90px" data-only="0 1">A4</i><i class="evict" style="width:90px" data-only="2 3 4">A4 ✗</i>'
                 '<i style="width:110px">A5</i><i style="width:90px">A7</i><i style="width:80px">A8·1</i><i style="width:70px">A8·2</i></div>')
    mem = ('<div class="mem" style="top:10px">'
           '<div class="m w" style="width:780px"><h4>Model weights</h4><small>unchanged</small></div>'
           '<div class="m e" style="width:280px"><h4>Workspace</h4><small>unchanged</small></div>'
           f'<div class="m kv" style="width:620px"><h4>KV cache pool</h4><small>full at this load</small>{pool_full}</div>'
           '</div>')
    host_pool = ('<div class="pool" style="left:30px;right:30px;bottom:20px;height:62px">'
                 '<i class="cold" style="width:240px">A4 · offloaded</i><i class="cold" style="width:220px">A2 · idle session</i>'
                 '<i class="cold" style="width:220px">A3 · idle session</i><i class="cold" style="width:220px">A6 · idle session</i>'
                 '<i class="free" style="border-color:var(--dw-line)">room for more cached state</i></div>')
    host = ('<div class="mem host" style="top:300px;height:140px" data-s="3">'
            f'<div class="m" style="width:1680px;background:var(--f-dim-soft)"><h4>CPU memory on the same node <small style="margin-left:14px">native KV offloading: a second tier for cached state</small></h4>{host_pool}</div>'
            '</div>')
    arrows = overlay(arrow(1330, 202, 1330, 298, 'c thick', 3, 'fund-ah-c'), arrow(1420, 298, 1420, 202, 'c thick dash', 3, 'fund-ah-c'))
    lbl = label(1460, 222, 220, '<small>offload ↓ · fetch back ↑<br>over PCIe or C2C</small>', 'l', 3)
    caps = ('<div class="memcap" style="top:465px;grid-template-columns:1fr 1fr 1fr;gap:40px">'
            '<p data-s="2"><strong>Pool full</strong>New requests wait for a free slot, or the engine throws out someone&#8217;s working state (A4 here) '
            'and recomputes it later. Either way the curve bends.</p>'
            '<p data-s="3"><strong>Spill to host memory</strong>With native CPU offloading, blocks the GPU had to drop go to host memory instead, '
            'including the prefixes of idle sessions. The next hit on that prefix copies them back rather than recomputing.</p></div>')
    return slide(
        'Where the limits come from',
        kick('1.6', 'Scaling: more traffic, same workload'),
        'The KV pool fills up before anything else does',
        mem + host + arrows + lbl + caps, steps=3,
        foot='That is all we will say about CPU offloading: no transfer internals, no config, no eviction policy. One caveat: the router only sees '
             'CPU-resident cache if the workers publish those events; turning offloading on does not do that by itself.',
        notes=(
            '<p>Once concurrency and cache pressure are established, expand the GPU-memory picture with CPU memory as an additional cache tier.</p>'
            + steps_note([
                'GPU cache capacity is finite; the engine can retain more cached state by using host memory as well.',
                'Present native CPU KV offloading as a way to increase the effective cache pool, without teaching transfer implementation, '
                'configuration options or eviction policies.',
                'Keep the distinction between cached request state and model weights explicit. More cache capacity does not add GPU compute.',
                'Then return to the need for another serving replica and its startup delay. Do not insert a new CPU-offloading topic between '
                'routing and KVCR later.'])
            + '<p class="dw-dim">Qualify the selected Super VL configuration and router-visible tier events only if offloading is demonstrated; '
            'the capacity visual before ModelExpress needs no separate offload benchmark. Block sizes on the slide are illustrative.</p>'))


def c4_replica():
    def ln(text, only=None):
        at = f' data-only="{only}"' if only else ''
        return f'<span class="ln"{at}>{text}</span>'
    code = (ln('<span class="k">spec</span>:')
            + ln('  <span class="k">components</span>:')
            + ln('  - <span class="k">name</span>: worker')
            + ln('    <span class="k">type</span>: <span class="v">worker</span>')
            + ln('    <span class="k">replicas</span>: <span class="p">2</span>        <span class="c"># was 1</span>', '1 2 3 4')
            + ln('<span class="c"># kubectl apply -f agent-baseline.yaml</span>'))
    left = f'<div class="code sm" style="position:absolute;left:0;top:0;width:620px;height:205px" data-s="1">{code}</div>'
    side = ('<div class="banner" style="left:660px;top:0;width:1020px;height:205px" data-s="1">'
            '<span>We scale by hand. Change the replica count, apply, and the operator starts a second worker. '
            'The agents notice nothing until it is Ready.<small>Automated scaling gets one overview slide later on; there is no Planner demo.</small></span></div>')
    total, w_load, w_init = 493, 267, 144
    other = total - w_load - w_init
    px = 1680 / total
    tl = ('<div class="tl" style="top:285px" data-s="2">'
          f'<div class="ph o" style="width:{other * px:.0f}px"><h4>Everything else</h4><small>{other} s</small></div>'
          f'<div class="ph w" style="width:{w_load * px:.0f}px"><h4>Model weight loading</h4><small>{w_load} s · from the same storage path</small></div>'
          f'<div class="ph i" style="width:{w_init * px:.0f}px"><h4>Engine initialization</h4><small>{w_init} s</small></div>'
          '</div>')
    tick0 = '<div class="tick" style="left:2px;top:255px;height:190px" data-s="2"><span style="right:auto;left:14px">replicas: 2 applied</span></div>'
    tick1 = f'<div class="tick" style="left:1676px;top:255px;height:190px" data-s="2"><span>Ready · {total} s · 8 min 13 s</span></div>'
    caps = ('<div class="tlcap" style="top:445px" data-s="3">'
            f'<div style="width:{other * px:.0f}px"><p><strong>Meanwhile</strong>Replica 1 keeps serving, still below target.</p></div>'
            f'<div style="width:{w_load * px:.0f}px"><p><strong>The same read, again</strong>Every new replica pulls the same checkpoint from the same storage. '
            'A replica that already holds the weights would be a faster source.</p></div>'
            f'<div style="width:{w_init * px:.0f}px"><p><strong>Still to come</strong>Compilation, warm-up, graph capture. ModelExpress can copy the '
            'compile caches too; Snapshot skips this part, in resiliency.</p></div></div>')
    banner = ('<div class="banner" style="left:0;top:585px;width:1680px;height:88px" data-s="4">'
              '<span>You asked for capacity eight minutes ago and still don&#8217;t have it. That wait is what ModelExpress is about.</span></div>')
    return slide(
        'Add a replica, then wait',
        kick('1.6', 'Scaling: more traffic, same workload'),
        'A second replica is one line, and then eight minutes',
        left + side + tl + tick0 + tick1 + caps + banner, steps=4,
        foot='Same measurement as section 1: Super VL TP2 on two H100s, native loading from EFS, one fixed-order run. '
             'An example, not a distribution.',
        notes=(
            '<p>Bring back the startup timeline from section 1. The audience now has a reason to care about its duration: the requested '
            'capacity has not yet become useful.</p>'
            + steps_note([
                'Native loading from the existing EFS checkpoint took about 493 s to observed Ready, including 267 s of model loading and 144 s '
                'of engine initialization. Model loading is the largest individually logged phase, about 54% of full startup.',
                'This baseline includes no external model download and is not a cold-Hugging-Face or local-NVMe comparison.',
                'Hardware framing for the next section: storage and download paths have finite bandwidth; an existing compatible replica already '
                'holds the processed weights in GPU memory, and GPU peer connectivity offers another source and transfer path.'])))


# ----------------------------------------------------------------------------- 2.5 disaggregation
DIS = kick('2.5', 'Disaggregated serving')


def g1_why():
    pre = card('g', 'Prefill reads the prompt',
               '<ul><li>One forward pass over every input token, all in parallel.</li>'
               '<li><b>Compute-bound</b>: a long prompt can keep an H100&#8217;s 989 TFLOPS busy.</li>'
               '<li>Its duration is the <b>time to first token</b>.</li>'
               '<li>Likes a low tensor-parallel degree and batches measured in tokens.</li></ul>', 'phase 1', 1)
    dec = card('c', 'Decode writes the answer',
               '<ul><li>One token per step for every active request, reading the weights and the KV cache each step.</li>'
               '<li><b>Memory-bound</b>: against 3.35 TB/s of HBM the compute units mostly wait.</li>'
               '<li>Its step time is the <b>inter-token latency</b>.</li>'
               '<li>Likes a high tensor-parallel degree and many requests per batch.</li></ul>', 'phase 2', 1)
    cards = f'<div class="cards c2" style="width:1680px">{pre}{dec}</div>'
    dec_steps = ''.join(f'<rect class="dec" x="{x}" y="392" width="30" height="44" rx="6" data-s="2"/>' for x in range(0, 460, 38))
    dec_steps2 = ''.join(f'<rect class="dec" x="{x}" y="392" width="30" height="44" rx="6" data-s="2"/>' for x in range(1230, 1680, 38))
    strip = overlay(
        '<text class="d" x="0" y="372" data-s="2">one aggregated engine, step by step →</text>',
        dec_steps,
        '<rect class="pre" x="480" y="392" width="730" height="44" rx="6" data-s="2"/>',
        '<text x="845" y="421" text-anchor="middle" style="fill:#0b1200" data-s="2">prefill for request D · 8,000 tokens · one step</text>',
        dec_steps2,
        '<text class="d" x="0" y="470" data-s="2">decode steps for A, B and C: one token each, every few milliseconds</text>',
        '<path class="r" d="M484 448 v12 h722 v-12" data-s="3"/>',
        '<text class="r" x="845" y="488" text-anchor="middle" data-s="3">A, B and C get no token until D&#8217;s prompt is done</text>')
    banner = ('<div class="banner" style="left:0;top:520px;width:1680px;height:130px" data-s="3">'
              '<span>Continuous batching runs both phases in one engine, so one long prompt stalls every active stream. And the hardware is '
              'mismatched either way: while decode runs the compute sits idle, while prefill runs the memory bandwidth does.'
              '<small>GPU figures are H100 SXM numbers from the sources; the interference looks the same on any GPU.</small></span></div>')
    return slide(
        'Why disaggregation',
        DIS,
        'Prefill and decode fight over the same GPU',
        cards + strip + banner, steps=3,
        foot='The two phases from section 1 again, now as a scheduling problem: they want different hardware, different batches and '
             'different parallelism, and they take turns on the same engine.',
        notes=(
            '<p>Open with the two phases from fundamentals and make their different demands the motivation.</p>'
            '<ul><li>Prefill processes the whole prompt in one pass and is compute-bound; decode produces one token per step per request and '
            'is bound by memory bandwidth, because every step reads the weights and the KV cache.</li>'
            '<li>In one engine with continuous batching a long prompt is a long step: every stream that is decoding waits for it '
            '(head-of-line blocking). That is the inter-token-latency spike users notice.</li>'
            '<li>Each phase also prefers a different configuration: low tensor parallelism cuts communication during prefill, high tensor '
            'parallelism helps the memory operations of decode. One engine has to pick one.</li></ul>'
            '<p class="dw-dim">Sources: NVIDIA&#8217;s Dynamo launch post; the Spheron and ClusterBid guides to disaggregated inference. '
            'Keep it at this level: no kernel or tuning tutorial.</p>'))


def g2_what():
    fe = node(0, 230, 300, 190, '<h3>Frontend<small>router</small></h3><p>Takes the request, picks a prefill worker and a decode worker for it.</p>', 'g', 1)

    def wk(x, y, w, h, title, sub, cls, s, gpus=2):
        g = '<div class="gpu">' + '<i></i>' * gpus + '</div>'
        return f'<div class="wk {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px" data-s="{s}"><h4>{title}</h4><small>{sub}</small>{g}</div>'
    pf_frame = '<div class="frame" style="left:400px;top:0;width:500px;height:500px" data-s="2"><span>prefill pool · x workers · sized for prompt load</span></div>'
    pf = (wk(430, 50, 440, 125, 'prefill 1', 'TP2 · big token batches · small KV pool', 'g', 2)
          + wk(430, 195, 440, 125, 'prefill 2', 'same model, same weights', 'g', 2)
          + '<div class="wk ghost" style="left:430px;top:345px;width:440px;height:125px" data-s="4"><h4>+ prefill 3</h4><small>when prompts pile up</small></div>')
    de_frame = '<div class="frame" style="left:1080px;top:0;width:600px;height:500px" data-s="3"><span>decode pool · y workers · sized for concurrency and output</span></div>'
    de = (wk(1110, 50, 540, 100, 'decode 1', 'TP8 · many requests · large KV pool', 'c', 3, 4)
          + wk(1110, 170, 540, 100, 'decode 2', 'steps limited by memory bandwidth', 'c', 3, 4)
          + wk(1110, 290, 540, 100, 'decode 3', 'same model, same weights', 'c', 3, 4)
          + '<div class="wk ghost" style="left:1110px;top:410px;width:540px;height:60px" data-s="4"><h4>+ decode 4</h4><small>when generation slows down</small></div>')
    arrows = overlay(
        arrow(300, 325, 400, 325, '', 2),
        arrow(900, 230, 1080, 230, 'c thick', 3, 'fund-ah-c'),
        arrow(1080, 440, 300, 380, 'c dash', 3, 'fund-ah-c', mid=(700, 560)))
    lbl = label(902, 150, 176, '<small>KV cache over <b>NIXL</b><br>once per request</small>', '', 3)
    lbl2 = label(560, 520, 420, '<small>tokens stream back through the frontend</small>', '', 3)
    caps = ('<div class="memcap" style="top:560px;grid-template-columns:1fr 1fr 1fr;gap:36px">'
            '<p data-s="4"><strong>Own engine settings</strong>Parallelism, batch size and KV pool are tuned per phase, not compromised across both.</p>'
            '<p data-s="4"><strong>Own replica count</strong>x prefill and y decode workers, changeable at runtime: a new worker registers with discovery and the router starts using it.</p>'
            '<p data-s="4"><strong>Even different GPUs</strong>Compute-heavy parts for prefill, bandwidth and capacity for decode, if your cluster has both.</p></div>')
    return slide(
        'What it is',
        DIS,
        'Give each phase its own pool of workers',
        fe + pf_frame + pf + de_frame + de + arrows + lbl + lbl2 + caps, steps=4,
        foot='NVIDIA&#8217;s launch example for Llama 70B on Hopper: TP8 for everything became TP2 prefill workers plus TP8 decode workers.',
        notes=(
            '<p>Disaggregated serving: prefill and decode run on separate workers, each pool with its own engine configuration, its own '
            'parallelism and its own replica count. The KV cache a prefill worker builds is moved to the decode worker that continues the '
            'request. Dynamo calls the shape xPyD: x prefill workers, y decode workers, reconfigurable at runtime.</p>'
            '<ul><li>Workers register with discovery and publish their runtime configuration, including KV capacity; the router discovers '
            'new workers automatically. Removal drains active requests first.</li>'
            '<li>Operators sometimes use different GPUs per pool: compute-heavy parts for prefill, high-bandwidth, high-capacity parts for '
            'decode. The workshop cluster is homogeneous H100s, so we only split roles.</li></ul>'
            '<p class="dw-dim">Sources: Dynamo design docs (disaggregated serving), the NVIDIA launch post, ClusterBid&#8217;s operator guide.</p>'))


def g3_flow():
    agent = node(0, 270, 230, 150, '<h3>Agent<small>HTTP client</small></h3><p>One streaming request.</p>', '', 1)
    fe = node(300, 250, 340, 190, '<h3>Frontend<small>① preprocess and route</small></h3><p>Picks a prefill worker by <b>cache overlap and load</b>, then a decode worker.</p>', 'g', 1)
    pf = node(740, 20, 440, 215, '<h3>Prefill worker<small>② build the state</small></h3><p>Runs the whole prompt once and builds the KV cache. '
              'Hands back <b>transfer metadata</b>: which blocks, where.</p>', 'g', 2)
    de = node(1240, 330, 440, 240, '<h3>Decode worker<small>④ pull, then ⑤ generate</small></h3><p>Fetches the KV blocks straight into its own GPU memory, '
              'then generates token by token and streams them back.</p>', 'c', 4)
    arrows = overlay(
        arrow(230, 345, 300, 345, '', 1),
        arrow(640, 300, 740, 150, 'g', 2, 'fund-ah-g', mid=(700, 300)),
        arrow(640, 380, 1240, 420, 'c', 3, 'fund-ah-c', mid=(940, 560)),
        arrow(1180, 160, 1240, 370, 'c thick dash', 4, 'fund-ah-c', mid=(1232, 160)),
        arrow(1240, 540, 640, 430, 'c', 5, 'fund-ah-c', mid=(900, 640)))
    lbl3 = label(760, 455, 400, '③ the router forwards the request to the decode worker<small>with the prefill worker&#8217;s transfer metadata attached</small>', 'l', 3)
    lbl4 = label(930, 262, 290, '④ KV blocks, GPU to GPU<small><b>NIXL</b>: NVLink inside a node, RDMA across nodes. Non-blocking, other requests keep running.</small>', '', 4)
    lbl5 = label(680, 585, 420, '⑤ tokens stream back to the agent', 'l', 5)
    banner = ('<div class="banner" style="left:0;top:625px;width:640px;height:60px;padding:12px 22px;font-size:20px" data-s="5">'
              '<span>vLLM and TensorRT-LLM finish the prefill before decode starts; SGLang can start decoding while the transfer is still in flight.</span></div>')
    return slide(
        'How a request flows',
        DIS,
        'One request, step by step',
        agent + fe + pf + de + arrows + lbl3 + lbl4 + lbl5 + banner, steps=5,
        foot='The transfer is the only new step. Everything else is the aggregated path split in two, with the frontend holding the request together.',
        notes=(
            '<p>The flow as the Dynamo design docs describe it. The frontend passes the preprocessed request to the PrefillRouter, which '
            'drives both halves.</p>'
            '<ol><li>Prefill worker selection: KV-aware routing (cache overlap scores weighed against load) or plain load balancing.</li>'
            '<li>The prefill worker computes the KV cache and returns <code>disaggregated_params</code>, backend-specific transfer metadata: '
            'for vLLM, <code>kv_transfer_params</code> with block ids and the remote worker&#8217;s connection info; for SGLang, '
            '<code>bootstrap_info</code>; for TensorRT-LLM, an opaque state.</li>'
            '<li>The router selects a decode worker and sends it the decode request with that metadata injected.</li>'
            '<li>The decode worker coordinates with the prefill worker and NIXL moves the KV cache directly from prefill VRAM to decode VRAM '
            'over the best available transport (NVLink, InfiniBand or RoCE via UCX, TCP as the slow fallback). The transfer is non-blocking: '
            'forward passes keep serving other requests meanwhile.</li>'
            '<li>Decode generates and streams tokens to the frontend. With vLLM and TensorRT-LLM prefill runs synchronously and decode waits for '
            'it; SGLang can run prefill as a background task so decode starts while the transfer proceeds.</li></ol>'
            '<p class="dw-dim">The NIXL log line to look for on a prefill worker: "NIXL INFO Backend UCX was instantiated".</p>'))


def g4_gains():
    c1 = card('g', 'Isolation',
              '<p>A 32K-token prompt lands in the prefill pool and no stream in the decode pool skips a beat. Steadier inter-token latency, '
              'and a time to first token that does not depend on who else is generating.</p>', 'no interference', 1)
    c2 = card('c', 'The right shape for each phase',
              '<p>Prefill wants <b>low tensor parallelism and token-heavy batches</b>; decode wants <b>high tensor parallelism and many '
              'concurrent sequences</b>. One engine has to pick a compromise between them; two pools do not.</p>', 'per-phase configuration', 2)
    c3 = card('a', 'Sized and scaled separately',
              '<p>Prefill replicas follow prompt load, decode replicas follow concurrency and output length. Operators start around one prefill '
              'worker per two or three decode workers, one to one for 32K+ contexts, then profile. Later the Planner can move the counts on a timer.</p>', 'x prefill, y decode', 3)
    cards = f'<div class="cards c3" style="width:1680px">{c1}{c2}{c3}</div>'
    banner = ('<div class="banner" style="position:relative;width:1680px;margin-top:26px;height:auto" data-s="4">'
              '<span>On the frontier from slide 14 this is a shift up and to the right: more tokens per megawatt at the same speed per user, or more '
              'speed per user at the same cost. The gain is largest with long prompts, long outputs or high concurrency.'
              '</span></div>')
    return slide(
        'What it buys',
        DIS,
        'What disaggregation buys you',
        cards + banner, steps=4,
        foot='Numbers are NVIDIA&#8217;s, for those exact setups. Our own Super VL measurement closes this section: the isolation shows up in the tails, not in throughput.',
        notes=(
            '<p>Three benefits, in the order they matter for the coding-agent workload.</p>'
            '<ul><li>Isolation: separating long-context prefills keeps ongoing decode requests from being blocked, which shows up as steadier '
            'ITL and a TTFT that no longer depends on the decode batch.</li>'
            '<li>Fit: each phase gets its own parallelism and batch configuration. NVIDIA&#8217;s launch post: Llama 70B on Hopper, vLLM FP8, '
            'ISL/OSL 3K/50, baseline TP8·DP2 against context TP2·DP4 plus generation TP8, more than doubled throughput. DeepSeek-R1 671B on '
            'GB200 NVL72, TensorRT-LLM FP4, ISL/OSL 32K/8K, baseline in-flight batching TEP16·PP4·DP4 against context EP4·DP16 plus '
            'generation EP64·DP3, up to 30× requests served, labelled projected.</li>'
            '<li>Independent sizing: ratios from operator guides (1:2 or 1:3 prefill to decode, 1:1 for 32K+ contexts; start there and '
            'profile). The Planner from the autoscaling section can adjust the counts.</li></ul>'
            '<p class="dw-dim">Our November 4 comparison (last slide of this section) showed the isolation benefit as better tails, with '
            'unchanged throughput and slower medians. It does not show the fit or sizing gains.</p>'))


def g5_costs():
    c1 = card('r', 'Every KV cache crosses the fabric once',
              '<p>Llama 3.1 70B, FP16 KV: 80 layers × 2 × 8 heads × 128 × 2 bytes is <b>320 KB per token</b>, so an 8K prompt is <b>about 2.6 GB</b>.</p>'
              '<table class="kt"><tr><td>NVLink, 450 GB/s each way</td><td><b>≈ 6 ms</b></td></tr>'
              '<tr><td>InfiniBand 400 Gb/s</td><td><b>≈ 52 ms</b></td></tr>'
              '<tr><td>100 GbE, TCP fallback</td><td><b>≈ 210 ms</b></td></tr></table>'
              '<p>A few milliseconds vanish at hundreds of requests per second. A fifth of a second does not.</p>', 'the transfer', 1)
    c2 = card('a', 'More to run and to size',
              '<ul><li>A second pool to size. Get the ratio wrong and prefill GPUs sit idle while decode queues, or the other way round.</li>'
              '<li>A router that pairs workers, discovery, transfer metadata, warm-up for cold transfers.</li>'
              '<li>On Kubernetes: RDMA device plugins, <code>IPC_LOCK</code>, and room in <code>/dev/shm</code> for NIXL.</li></ul>', 'the plumbing', 2)
    c3 = card('c', 'Leave it off when',
              '<ul><li>The model is small, prompts are short or concurrency is low.</li>'
              '<li>There is no fast fabric between the pools.</li>'
              '<li>One 8-GPU node serves a few hundred internal users: aggregated with prefix caching wins.</li></ul>'
              '<p>The docs say it plainly: in these cases an aggregated deployment is simpler and often faster.</p>', 'the judgement', 3)
    cards = f'<div class="cards c3" style="width:1680px">{c1}{c2}{c3}</div>'
    return slide(
        'What it costs',
        DIS,
        'What it costs, and when to skip it',
        cards, steps=3,
        foot='KV sizes are for FP16 caches; FP8 halves them. Bandwidths are per-direction peaks, so real transfers take longer than the table.',
        notes=(
            '<p>Costs first, then the decision.</p>'
            '<ul><li>Transfer: the whole KV cache of every request moves once. Size it for your model: per token, layers × 2 (K and V) × KV heads '
            '× head dimension × bytes. Llama 3.1 70B with GQA (8 KV heads) and FP16 is 320 KB per token, 2.6 GB for 8K tokens. Over NVLink that '
            'is a few milliseconds; over 400 Gb/s InfiniBand about 50 ms; over 100 GbE with the TCP fallback about 200 ms, which is why the '
            'operator guides call standard Ethernet too slow for this path.</li>'
            '<li>Plumbing: a router that pairs workers, discovery, backend-specific transfer metadata, warm-up (cold transfers inflate TTFT), '
            'RDMA plugins and shared memory on Kubernetes.</li>'
            '<li>When not to: small models, short prompts, low concurrency, no fast fabric. ClusterBid&#8217;s rule of thumb wants all of: models '
            'above 70B, 16 or more GPUs, InfiniBand or RoCE, sustained traffic. The Dynamo docs: an aggregated deployment is simpler and often '
            'faster in those cases.</li></ul>'))


def g6_dynamo():
    def ln(text, only=None):
        at = f' data-only="{only}"' if only else ''
        return f'<span class="ln"{at}>{text}</span>'
    code = (ln('<span class="k">spec</span>:')
            + ln('  <span class="k">components</span>:')
            + ln('  - <span class="k">name</span>: Frontend')
            + ln('    <span class="k">type</span>: <span class="v">frontend</span>        <span class="c"># routes, pairs prefill and decode</span>')
            + ln('  - <span class="k">name</span>: prefill', '1')
            + ln('    <span class="k">type</span>: <span class="v">worker</span>', '1')
            + ln('    <span class="k">subComponentType</span>: <span class="v">prefill</span>', '1')
            + ln('    <span class="k">replicas</span>: <span class="p">1</span>', '1')
            + ln('    <span class="k">args</span>: [--model, nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4,', '1')
            + ln('           --tensor-parallel-size, <span class="p">"2"</span>, <span class="v">--disaggregation-mode</span>, <span class="v">prefill</span>]', '1')
            + ln('  - <span class="k">name</span>: decode', '2')
            + ln('    <span class="k">type</span>: <span class="v">worker</span>', '2')
            + ln('    <span class="k">subComponentType</span>: <span class="v">decode</span>', '2')
            + ln('    <span class="k">replicas</span>: <span class="p">1</span>', '2')
            + ln('    <span class="k">args</span>: [--model, nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4,', '2')
            + ln('           --tensor-parallel-size, <span class="p">"2"</span>, <span class="v">--disaggregation-mode</span>, <span class="v">decode</span>]', '2')
            + ln('<span class="c"># both pools: same model, dtype, block size, KV layout</span>')
            + ln('<span class="c"># NIXL: sharedMemory 16Gi; RDMA resources across nodes</span>'))
    left = f'<div class="code sm" style="position:absolute;left:0;top:0;width:900px;height:520px">{code}</div>'
    right = ('<div style="position:absolute;left:940px;top:0;width:740px;display:flex;flex-direction:column;gap:20px">'
             + card('c', 'Also in the box: EPD for multimodal',
                    '<p>A third pool runs the vision encoder and ships <b>embeddings</b> over NIXL. With 10 images per request TTFT fell 50 to 58%; '
                    'with mixed traffic, text requests stopped waiting behind image ones. Small gain or a loss for large dense models and long outputs.</p>', s=3)
             + card('a', 'Measured: same throughput, better tails',
                    '<p>Super VL on four H100s, AgentX at concurrency 16: two aggregated TP2 workers against TP2 prefill + TP2 decode. '
                    'Throughput unchanged (<b>174.8 vs 174.4 tok/s</b>); tails better (p99 TTFT <b>5.1 → 3.1 s</b>, p99 ITL <b>20.3 → 10.7 ms</b>); '
                    'medians slower (p50 TTFT 255 → 317 ms). The demo shows one KV handoff; then back to aggregated serving.</p>', s=4)
             + '</div>')
    return slide(
        'How Dynamo does it',
        DIS,
        'How Dynamo does it, and what we measured',
        left + right, steps=4,
        foot='Older releases used <code>--is-prefill-worker</code>; check <code>python3 -m dynamo.vllm --help</code> in the pinned image. '
             'The manifest mirrors the simplified section 1 style; the docs ship full <code>disagg.yaml</code> templates per backend.',
        notes=(
            '<p>Two services instead of one worker, each with its own replicas. Prefill and decode must use the same model, dtype, block size '
            'and KV layout. NIXL stages metadata through /dev/shm, so the pods need a larger shared-memory size (the guide uses 16Gi); '
            'cross-node transfer needs RDMA resources (InfiniBand or RoCE), otherwise it falls back to TCP.</p>'
            '<ul><li>EPD (encode, prefill, decode) for multimodal models: encoder workers run the vision transformer and send embeddings to '
            'the PD workers over NIXL. In NVIDIA&#8217;s digest, TTFT dropped 58% with colocated encoders and 50% with a separate encoder tier at '
            '10 images per request; under 50/50 mixed traffic text TTFT fell 42%. Gains shrink with long outputs and large dense models, and '
            'a homogeneous disaggregated-encoder setup underperformed colocation.</li>'
            '<li>Demo: demos/03-disaggregated proves the transfer path, not a performance gain. The measurement '
            '(reports/overnight-2026-11-04/disagg/RESULTS.md) is one point, C16 on four H100s: a latency trade, not a throughput win, so do not '
            'present it as a speedup. Return to aggregated serving explicitly before the resiliency section.</li></ul>'))


# ----------------------------------------------------------------------------- 2.6 autoscaling: a short introduction to the Planner
def a1_planner():
    fe = node(0, 50, 420, 270, '<h3><small>what it watches</small>Traffic and engine metrics</h3>'
              '<p>Requests per second, prompt and output lengths, and from the engines: TTFT, ITL, queue depth and KV usage.</p>', 'a', 1)
    pl = node(540, 50, 480, 270, '<h3><small>what it decides</small>How many engines to run</h3>'
              '<p>A replica count for prefill and one for decode, recomputed every few seconds from your targets and a performance model.</p>', 'a', 2)
    out = node(1140, 50, 540, 270, '<h3><small>what it writes</small>The replicas lines in your DGD</h3>'
               '<p>The operator and Grove take it from there and place whole instances. Planner itself runs as a service inside the same DGD.</p>', 'g', 3)
    arrows = overlay(arrow(420, 185, 540, 185, '', 2), arrow(1020, 185, 1140, 185, '', 3))
    banner = ('<div class="banner" style="left:0;top:400px;width:1680px;height:160px" data-s="4">'
              '<span>In this workshop we scale by hand. This is the one overview of automated scaling, and there is no Planner demo. '
              'The next two slides show what you set, and what the number it writes actually scales.'
              '<small>Behaviour and defaults are from the Dynamo v1.5.1 Planner docs; the two slides that follow come from the Planner × Grove deck on ai-dynamo.org.</small></span></div>')
    return slide(
        'Dynamo Planner',
        kick('2.6', 'Autoscaling'),
        'The Planner is Dynamo&#8217;s autoscaler',
        MARKERS + fe + pl + out + arrows + banner, steps=4,
        sub='It runs inside your deployment and decides, on a timer, how many prefill and decode engines to run.',
        notes=(
            '<p>Automated scaling overview, one slide plus two borrowed ones; the workshop experiments continue to use manual scaling.</p>'
            + steps_note([
                'Planner (<code>dynamo.planner</code>) is the autoscaler: it decides how many prefill and decode engines a deployment should '
                'run. Grove (ai-dynamo/grove) turns those counts into complete, gang-scheduled model instances. Planner never calls Grove: '
                'the Dynamo operator reconciles the DGD into Grove resources.',
                'Each tick: observe worker counts, traffic metrics and per-iteration engine metrics; predict next-interval request count, ISL '
                'and OSL; propose replica counts (a forecast loop sets a floor, a live loop adjusts by one); apply minimums and the GPU budget; '
                'execute through the connector. The base tick is normally 5 s; the forecast loop runs every 180 s.',
                'Why not an HPA: prefill and decode need separate counts sized on TTFT and ITL; demand is tokens, not requests; capacity is '
                'multi-node and must be placed whole.',
                'Operating notes from the source deck: interval at least time-to-ready, averages hide bimodal ISL, one autoscaler per '
                'service, no scale-to-zero for workers, the GPU budget is not cluster capacity.'])
            + '<p class="dw-dim">Source deck: ai-dynamo.org/slides/planner-grove.html (docs baseline Dynamo v1.5.1, Planner source on main). '
            'The outline allows at most one general overview slide on automated scaling and no Planner demonstration.</p>'))


SLIDES = [c1_agents, c2_curve, c3_limits, c4_replica, g1_why, g2_what, g3_flow, g4_gains, g5_costs, g6_dynamo, a1_planner]


def render_slides():
    return [f() for f in SLIDES]


if __name__ == '__main__':
    for i, h in enumerate(render_slides()):
        print(i, len(h))
