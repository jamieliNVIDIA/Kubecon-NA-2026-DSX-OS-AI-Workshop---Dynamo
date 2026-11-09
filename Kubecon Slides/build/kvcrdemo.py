"""KVCR pieces authored for the Dynamo workshop deck (outline 2.4): the demo cue for stop 5 and the closing "Try KVCR" slide.
Same conventions and visual language as fundamentals.py, whose CSS and helpers are reused; built as the 'kvcrdemo' deck and
placed by PROGRAM in build.py around slides of the ai-dynamo.org KVCR and intro decks.
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
/* ===== KVCR demo cue: two workers, repositories A and B ===== */
.kt{display:flex;align-items:center;gap:14px;height:50px;flex:none;border-radius:12px;padding:0 18px;background:var(--f-green-soft);border:1px solid var(--f-green-line);font-size:20px;color:var(--dw-text);white-space:nowrap}
.kt b{font:700 18px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-green-ink)}
.kt.e{background:transparent;border:2px dashed var(--f-cyan-line);color:var(--dw-dim)}
.kt.e b{color:var(--dw-cyan)}
.demo.c5{grid-template-columns:repeat(5,1fr);gap:16px}
.demo.c5 .card{padding:22px 20px;gap:12px}
.demo.c5 .card h3{font-size:24px}
.demo.c5 .card p{font-size:18px}
.demo.c5 .card .chip{font-size:14px;padding:7px 10px}
/* ===== Try KVCR ===== */
.eng{position:absolute;display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.eng div{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;height:120px;border-radius:16px;background:var(--dw-surface);border:2px solid var(--dw-green-fill);box-shadow:var(--dw-shadow);font:700 30px/1 Inter,sans-serif}
.eng div.soon{border-style:dashed;border-color:var(--f-amber-line)}
.eng span{font:700 15px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;border-radius:999px;padding:6px 12px;color:#0b1200;background:var(--dw-green-fill)}
.eng div.soon span{color:var(--f-amber);background:var(--f-amber-soft)}
.kbar{position:absolute;display:flex;align-items:center;gap:20px;border-radius:16px;padding:0 28px;height:96px;background:var(--dw-green-fill);color:#0b1200;font:600 23px/1.3 Inter,sans-serif}
.kbar b{font:800 38px/1 Inter,sans-serif}
.kopt{position:absolute;display:flex;align-items:center;justify-content:space-between;border-radius:16px;padding:0 28px;height:64px;border:2px dashed var(--dw-line);color:var(--dw-dim);font:600 23px/1 Inter,sans-serif}
.kopt small{font:600 15px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase}
.kpip{position:absolute;border-radius:16px;background:#12161b;color:#e8edf2;padding:22px 30px;font:600 34px/1.2 "JetBrains Mono",ui-monospace,Menlo,monospace;box-shadow:var(--dw-shadow)}
.kpip small{display:block;font:500 15px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.1em;color:#8b96a3;margin-bottom:14px;text-transform:uppercase}
.kqr{position:absolute;display:flex;align-items:center;gap:28px}
.kqr svg{flex:none;width:184px;height:184px;background:#fff;border-radius:14px;padding:14px;box-shadow:var(--dw-shadow)}
.kqr b{display:block;font:700 30px/1.2 Inter,sans-serif}
.kqr span{display:block;font:500 22px/1.4 "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);margin-top:6px}
.kst{position:absolute;display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.kst div{display:flex;flex-direction:column;gap:8px;border-radius:14px;padding:16px 20px;background:var(--dw-surface);border:1px solid var(--dw-line)}
.kst b{font:700 21px/1.25 Inter,sans-serif}
.kst i{align-self:flex-start;font:700 13px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;font-style:normal;letter-spacing:.1em;text-transform:uppercase;border-radius:999px;padding:6px 10px}
.kst i.rel{color:var(--dw-green-ink);background:var(--f-green-soft)}
.kst i.exp{color:var(--dw-cyan);background:var(--f-cyan-soft)}
.kst i.dev{color:var(--f-amber);background:var(--f-amber-soft)}
.kst i.pin{color:var(--f-rose);background:var(--f-rose-soft)}
"""

# Live speedup run on the workshop placement, November 9 at 09:19 UTC, in the five-step flow: demos/transcripts/live/07-kvcr/20261109-a1
LIVE = {'cold_a_ms': 2435, 'cold_b_ms': 2517, 'kvcr_b_ms': 317, 'speedup': 7.94, 'prompt': '58K', 'pages': 13,
        'reused': 54912, 'gib': 0.29, 'blocks': 18}

# QR code for https://github.com/ai-dynamo/kvcr (segno 1.6.1, version 3, error level M, no border): path of 1-unit strokes.
KVCR_QR = (
    'M0 0.5h7m3 0h2m3 0h4m3 0h7m-29 1h1m5 0h1m1 0h4m1 0h2m1 0h1m3 0h1m1 0h1m5 0h1m-29 1h1m1 0h3m1 0h1m1 0h1m4 0h1m1 0h1m2 0h1m1 0h1m1 0h1m1 '
    '0h3m1 0h1m-29 1h1m1 0h3m1 0h1m1 0h1m1 0h2m4 0h2m1 0h2m1 0h1m1 0h3m1 0h1m-29 1h1m1 0h3m1 0h1m2 0h1m1 0h2m2 0h3m1 0h1m2 0h1m1 0h3m1 0h1m-29 '
    '1h1m5 0h1m2 0h1m2 0h1m2 0h1m2 0h1m1 0h1m1 0h1m5 0h1m-29 1h7m1 0h1m1 0h1m1 0h1m1 0h1m1 0h1m1 0h1m1 0h1m1 0h7m-21 1h1m2 0h1m2 0h3m-17 1h1m5 '
    '0h1m1 0h1m1 0h1m6 0h1m1 0h1m1 0h2m2 0h3m-28 1h4m1 0h1m1 0h1m3 0h3m2 0h4m1 0h1m1 0h2m1 0h2m-28 1h2m4 0h1m6 0h3m1 0h1m2 0h1m3 0h1m-18 1h3m1 '
    '0h3m4 0h1m2 0h1m3 0h1m-22 1h3m1 0h1m1 0h2m1 0h1m1 0h2m2 0h2m1 0h2m4 0h1m-29 1h2m1 0h1m1 0h1m1 0h1m1 0h1m1 0h1m6 0h3m1 0h3m2 0h2m-28 1h2m3 '
    '0h2m7 0h1m2 0h1m1 0h2m2 0h3m-27 1h2m2 0h1m3 0h1m1 0h1m1 0h1m2 0h2m2 0h1m3 0h2m1 0h1m1 0h1m-27 1h2m2 0h1m1 0h1m6 0h3m1 0h1m1 0h1m1 0h1m1 '
    '0h2m-27 1h2m1 0h3m3 0h2m2 0h7m2 0h3m1 0h3m-29 1h2m2 0h1m1 0h3m1 0h3m2 0h1m1 0h1m1 0h1m4 0h2m2 0h1m-29 1h1m8 0h1m1 0h1m1 0h1m1 0h1m4 0h1m1 '
    '0h1m-23 1h1m1 0h2m1 0h2m3 0h3m1 0h2m1 0h1m1 0h6m1 0h3m-21 1h5m1 0h2m1 0h2m1 0h1m3 0h2m-26 1h7m3 0h3m2 0h1m1 0h1m1 0h2m1 0h1m1 0h3m-27 1h1m5 '
    '0h1m3 0h1m1 0h1m1 0h3m2 0h2m3 0h1m2 0h1m-28 1h1m1 0h3m1 0h1m6 0h3m2 0h8m1 0h2m-29 1h1m1 0h3m1 0h1m3 0h1m1 0h1m1 0h8m3 0h2m1 0h1m-29 1h1m1 '
    '0h3m1 0h1m4 0h1m2 0h4m1 0h9m-28 1h1m5 0h1m2 0h1m3 0h1m1 0h2m5 0h2m1 0h2m1 0h1m-29 1h7m1 0h1m2 0h2m4 0h1m1 0h1m2 0h3m1 0h1')


def demo_cards(steps):
    return ''.join(f'<div class="card"><span class="num">{n}</span><div><h3>{h}</h3><p>{p}</p><span class="chip">{esc(c)}</span></div></div>'
                   for n, h, p, c in steps)


# ----------------------------------------------------------------------------- 2.4 demo cue (runbook stop 5)
def k1_demo():
    def worker(x, cls, who, h3, tiles, chip):
        rows = ''.join(f'<div class="kt{e}"><b>{b}</b><span>{t}</span></div>' for e, b, t in tiles)
        return node(x, 0, 520, 290, f'<h3><small>{who}</small>{h3}</h3>{rows}<span class="chip">{esc(chip)}</span>', cls=cls)
    topo = (MARKERS
            + overlay(arrow(528, 156, 1150, 156, cls='g thick', head='fund-ah-g'))
            + worker(0, 'g', 'Worker A · node cp-0198', 'Main agent', [
                ('', 'HBM', 'repository A, being worked on'), ('', 'host pool', '58K tokens kept for reuse')], 'TP2 · warm')
            + worker(1160, 'c', 'Worker B · node cp-0942', 'Subagent', [
                (' e', 'HBM', 'never seen repository A'), (' e', 'host pool', 'empty for repository A')], 'TP2 · warm · spare compute')
            + label(540, 30, 600, '<b>&#9312; same prefix</b> the subagent forks the main agent&#8217;s context<small>a new task appended at the end</small>')
            + label(540, 196, 600, '<b>&#9313; pull</b> pages from A&#8217;s host pool to B<small>NIXL · LIBFABRIC over EFA · KVCR on both workers</small>'))
    steps = [   # the terminal's five steps, by the same titles
        ('1', 'One DGD, two engines', 'Engine A and engine B, each with a <b>KVCR service</b> beside it, and their KV config.',
         'kubectl get dgd'),
        ('2', 'Check the warm workers', 'Two TP2 engines, warmed offstage. Requests are <b>pinned</b> by hand.', 'kubectl get pods'),
        ('3', 'Main agent reads repository A on A', 'A computes all <b>58K tokens</b> and keeps them in its host pool.',
         'POST … pinned to A'),
        ('4', 'Two requests on B', 'Repository B: computed from scratch. Repository A: B <b>pulls 13 pages</b> from A.',
         'POST … pinned to B ×2'),
        ('5', 'Compare the first token', 'Same worker, same prompt size: recompute versus KVCR reuse.', 'speedup.json'),
    ]
    return slide(
        'Demo: the subagent lands on B',
        kick('2.4', 'Demo'),
        'Demo: the subagent lands on B',
        topo + f'<div class="demo c5" style="position:absolute;left:0;top:330px;width:1680px">{demo_cards(steps)}</div>',
        sub='Each answer names the file that defines a function planted once in its repository.',
        foot='Synthetic repositories built to show the mechanism: idle warm workers, one long shared prefix, requests pinned by hand. '
             'Experimental stack: Dynamo nightly with the vLLM KVCR adapter.',
        notes=(
            '<p>Presenter implementation: the KVCR terminal demo (<code>uv run python -m demos kvcr</code>), after <code>kvcr prepare</code> '
            'and <code>kvcr prime</code> offstage. Prime takes about 15 minutes: 12 to start both engines, then a warm-up that sends each '
            'engine its first request (the one that pauses about 18 s after its first token) and opens the A-to-B transfer path. '
            '<b>Start it early:</b> each engine downloads the pinned nightly wheels when its container starts. A cut-off download '
            'failed two primes before the bootstrap began retrying it in place; leave time for a fresh run anyway. Each onstage step '
            'takes seconds of cluster time.</p>'
            '<p><b>What to say.</b> The router section ended with a choice: wait for the busy worker that has the context, or recompute it '
            'on an idle one. KVCR adds a third option: copy the context. Step 1: one DGD, engine A on cp-0198 and engine B on cp-0942; '
            'each Pod runs the engine (<code>main</code>) and a <code>kvcr-services</code> sidecar with its own EFA device, and the KV '
            'config adds a 4 GiB host pool and a <code>kvcr</code> tier over LIBFABRIC. Step 2: both workers are warm. Step 3: the main '
            'agent reads repository A on A, computed from scratch: about 2.4 s to the first token. Step 4: on B, repository B (the same '
            'size and question, but no worker has read it) takes about 2.5 s; repository A takes about 0.3 s, because B pulls 13 of its '
            'pages from A instead of recomputing them. Every answer names the file where the function was planted.</p>'
            '<p><b>Close with the caveat</b>, which the terminal no longer prints: this is tailored to show the mechanism (warm idle '
            'workers, one long shared prefix, requests pinned by hand). Under real agent traffic the gain depends on load and reuse; the '
            'next slide has results on real workloads.</p>'
            f'<p><b>Last live run</b>, on the workshop placement (November 9, 09:19 UTC, cp-0198 to cp-0942), with the labels of the '
            f'table on screen: A &#183; repository A <b>{LIVE["cold_a_ms"]:,} ms</b>, B &#183; repository B '
            f'<b>{LIVE["cold_b_ms"]:,} ms</b>, B &#183; repository A <b>{LIVE["kvcr_b_ms"]} ms</b>: <b>{LIVE["speedup"]}&#215;</b> on '
            f'B. {LIVE["reused"]:,} tokens in {LIVE["blocks"]} blocks, {LIVE["gib"]} GiB over EFA, matched on both ends; every answer '
            'named its planted file. Earlier runs: 8.38&#215; on the same placement at 01:30 UTC (receipt '
            'reports/receipts/2026-11-09-kvcr-speedup-cp0942.json); with B on cp-0124, 7.84&#215; (a3) and 8.37&#215; (a2) on '
            'November 8, and seven extra rounds on warm workers 7.8&#8211;8.7&#215;. Quote the numbers on screen. Fallback: the '
            'recording at demos/transcripts/live/07-kvcr/20261109-a1, in the current five-step flow.</p>'
            '<p><b>Likely questions.</b> <i>Why so much faster?</i> Recomputing 58K tokens is a full prefill; the copy moves 0.29 GiB and '
            'recomputes only the last partial page (Super VL is a hybrid Mamba-attention model, so its per-token KV cache is small). '
            '<i>Always?</i> No: with a short shared prefix the copy saves little (an earlier 6K-token version saved about 60 ms). '
            '<i>Who chose B?</i> We '
            'did, by pinning; router-to-KVCR hints are experimental in Dynamo 1.5. <i>Guard?</i> Installed in the Pods but not exercised '
            'here; it is in resiliency.</p>'))


# ----------------------------------------------------------------------------- closing: try it
def k2_try():
    qr = f'<svg viewBox="0 0 29 29" shape-rendering="crispEdges" aria-label="QR code: github.com/ai-dynamo/kvcr"><path stroke="#000" d="{KVCR_QR}"/></svg>'
    body = (
        '<div class="kicker" style="position:absolute;left:0;top:0">Use KVCR on its own</div>'
        '<div class="eng" style="left:0;top:44px;width:820px"><div>vLLM<span>supported</span></div><div>SGLang<span>supported</span></div>'
        '<div class="soon">TRT-LLM<span>coming soon</span></div></div>'
        '<div class="kbar" style="left:0;top:190px;width:820px"><b>KVCR</b><span>KV cache offload, peer reuse and fault tolerance</span></div>'
        '<div class="kopt" style="left:0;top:304px;width:820px"><span>Rest of Dynamo: router hints, Planner, Grove</span><small>optional</small></div>'
        '<div class="kicker" style="position:absolute;left:900px;top:0">Start in one line</div>'
        '<div class="kpip" style="left:900px;top:44px;width:780px"><small>bash</small>$ pip install kvcr==0.1.1</div>'
        f'<div class="kqr" style="left:900px;top:186px">{qr}<div><b>Code, docs and examples</b><span>github.com/ai-dynamo/kvcr</span></div></div>'
        '<div class="kst" style="left:0;top:430px;width:1680px">'
        '<div><i class="rel">early release</i><b>KVCR 0.1.1 on PyPI</b></div>'
        '<div><i class="exp">experimental</i><b>Router-to-KVCR hints, Dynamo 1.5</b></div>'
        '<div><i class="dev">in development</i><b>KVCR-Guard</b></div>'
        '<div><i class="pin">this workshop</i><b>Dynamo nightly + vLLM KVCR adapter, pinned</b></div>'
        '</div>')
    return slide(
        'Try KVCR',
        kick('2.4', 'KVCR'),
        'Try KVCR with the engine you already run',
        body,
        foot='The workshop demo ran a pinned Dynamo nightly with the vLLM KVCR adapter; its image is not public yet. The package above '
             'is the public starting point.',
        notes=(
            '<p>Adapted from the KVCR team&#8217;s Berlin deck (&#8220;Get started with KVCR&#8221;). KVCR is a framework-neutral library: '
            'it plugs into vLLM or SGLang without the rest of Dynamo. Version 0.1.1 is the latest release on PyPI (October 16, 2026). The '
            'QR code opens github.com/ai-dynamo/kvcr.</p>'
            '<p><b>Maturity, consistently:</b> KVCR itself is an early release (the KVCR team reports an external production user on '
            '0.1.0); router-to-KVCR hints are experimental in Dynamo 1.5; KVCR-Guard is in development (resiliency section). The demo '
            'used matching Dynamo nightly wheels, a vLLM KVCR adapter and the KVCR preview service, pinned by hash.</p>'
            '<p class="dw-dim">Take-home: the demo&#8217;s base image sits in a private registry, so attendees cannot rerun the exact demo '
            'yet. Point them at the package and the repository examples.</p>'))


SLIDES = [k1_demo, k2_try]


def render_slides():
    return [f() for f in SLIDES]


if __name__ == '__main__':
    for i, h in enumerate(render_slides()):
        print(i, len(h))
