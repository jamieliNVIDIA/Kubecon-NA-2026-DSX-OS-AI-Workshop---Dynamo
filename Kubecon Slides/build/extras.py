"""Authored slides that PROGRAM places inside sections otherwise built from ai-dynamo.org decks.
Same conventions and visual language as fundamentals.py (helpers and CSS reused).
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
/* ===== snapshot benchmark chart ===== */
.bm{position:absolute;left:0;top:0;width:1680px;height:560px}
.bm text{font:500 17px Inter,sans-serif;fill:var(--dw-dim)}
.bm text.v{font:700 20px Inter,sans-serif;fill:var(--dw-text)}
.bm text.vg{font:700 20px Inter,sans-serif;fill:var(--dw-green-ink)}
.bm text.n{font:700 19px Inter,sans-serif;fill:var(--dw-text)}
.bm text.tp{font:600 16px "JetBrains Mono",ui-monospace,Menlo,monospace;fill:var(--dw-dim)}
.bm text.lg{font:600 18px Inter,sans-serif;fill:var(--dw-text)}
.bm .grid{stroke:var(--dw-line);stroke-width:2}
.bm .ax{stroke:var(--dw-line);stroke-width:4}
.bm .cold{fill:var(--dw-dim);opacity:.8}
.bm .snap{fill:var(--dw-green-fill)}
/* ===== ModelExpress demo cue: two replicas, rank to rank ===== */
.gt{display:flex;align-items:center;gap:14px;height:50px;flex:none;border-radius:12px;padding:0 18px;background:var(--f-green-soft);border:1px solid var(--f-green-line);font-size:20px;color:var(--dw-text);white-space:nowrap}
.gt b{font:700 18px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-green-ink)}
.gt.e{background:transparent;border:2px dashed var(--f-cyan-line);color:var(--dw-dim)}
.gt.e b{color:var(--dw-cyan)}
.demo.c4{grid-template-columns:repeat(4,1fr)}
.demo.c4 .card .chip{font-size:15px;padding:8px 12px}
/* ===== ModelExpress startup bars: the startup timeline from section 1, one row per loading path ===== */
.mxr{position:absolute;left:0;width:1680px;height:84px;display:flex;align-items:center}
.mxr .lb{flex:none;width:290px;display:flex;flex-direction:column;gap:6px}
.mxr .lb b{font:700 27px/1.1 Inter,sans-serif}
.mxr .lb small{font:500 18px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.mxr .bar{flex:none;display:flex;height:84px;border-radius:14px;overflow:hidden;border:1px solid var(--dw-line);box-shadow:var(--dw-shadow);background:var(--dw-surface)}
.mxr .bar span{flex:none;display:flex;align-items:center;justify-content:center;border-right:3px solid var(--dw-bg);font:700 22px "JetBrains Mono",ui-monospace,Menlo,monospace}
.mxr .bar span:last-child{border-right:none}
.mxr .o{background:var(--f-dim-soft)}.mxr .w{background:var(--f-green-soft)}.mxr .i{background:var(--f-amber-soft)}
.mxr .tot{flex:none;padding-left:24px;display:flex;flex-direction:column;gap:6px}
.mxr .tot b{font:800 30px/1 "JetBrains Mono",ui-monospace,Menlo,monospace}.mxr .tot b.g{color:var(--dw-green-ink)}
.mxr .tot small{font:500 18px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.mxc{position:absolute;left:0;width:1680px}
.mxc .card{padding:22px 26px 24px;gap:10px}
.mxc .card h3{font-size:27px}
.mxc .card p{font-size:20px;line-height:1.4}
/* ===== router opener: p90 turn latency on one worker and on two, by routing policy ===== */
.rt{position:absolute;left:0;width:1680px;height:64px;display:flex;align-items:center}
.rt .lb{flex:none;width:330px;display:flex;flex-direction:column;gap:5px}
.rt .lb b{font:700 25px/1.1 Inter,sans-serif}
.rt .lb small{font:500 17px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.rt .bar{flex:none;height:50px;border-radius:12px;border:1px solid var(--dw-line);box-shadow:var(--dw-shadow)}
.rt .bar.o{background:var(--f-dim-soft)}.rt .bar.a{background:var(--f-amber-soft)}.rt .bar.g{background:var(--f-green-soft)}
.rt .tot{flex:none;padding-left:22px}
.rt .tot b{font:800 30px/1 "JetBrains Mono",ui-monospace,Menlo,monospace}
.rt .tot b.a{color:var(--f-amber)}.rt .tot b.g{color:var(--dw-green-ink)}
.rtlg{position:absolute;left:330px;top:0;font:500 20px Inter,sans-serif;color:var(--dw-dim)}
.rtlg b{font-weight:700;color:var(--dw-text)}
.banner.tight{padding:12px 26px;font-size:21px}.banner.tight small{font-size:18px;margin-top:4px}
"""

# SGLang, B200 with VAST storage: cold start versus Snapshot restore (Snapshot blog draft, figure 3)
BENCH = [  # model name lines, parallelism, weights, cold start s, snapshot restore s
    (['Qwen3 0.6B'], 'TP1', '1.5 GB', 87.1, 3.6),
    (['Qwen3 14B'], 'TP1', '29.5 GB', 106, 5.6),
    (['Qwen3 14B'], 'TP2', '29.5 GB', 125, 7.5),
    (['gpt-oss 120b'], 'TP1', '65.3 GB', 269, 15.9),
    (['gpt-oss 120b'], 'TP4', '65.3 GB', 240, 29.6),
    (['GLM-5.3', 'NVFP4'], 'TEP8', '464.8 GB', 427, 35.3),
    (['DeepSeek-V4.1', 'Flash'], 'TEP8', '510.3 GB', 953, 36.5),
    (['DeepSeek-V4-Pro', 'NVFP4'], 'TEP8', '913.1 GB', 622, 42.7),
]


def b1_snapshot_bench():
    X0, X1, Y0, PXS = 90, 1660, 440, 0.4          # 0.4 px per second: 1000 s is 400 px tall
    gw = (X1 - X0) / len(BENCH)
    fmt = lambda v: f'{v:g}'
    grid = ''.join(f'<line class="grid" x1="{X0}" y1="{Y0 - v * PXS:.0f}" x2="{X1}" y2="{Y0 - v * PXS:.0f}"/>'
                   f'<text x="{X0 - 14}" y="{Y0 - v * PXS + 6:.0f}" text-anchor="end">{v:,}</text>' for v in range(200, 1001, 200))
    cold, snap, labels = '', '', ''
    for i, (name, tp, w, c, s) in enumerate(BENCH):
        gx = X0 + i * gw
        xc, xs = gx + 36, gx + 104
        hc, hs = c * PXS, s * PXS
        cold += (f'<rect class="cold" x="{xc:.0f}" y="{Y0 - hc:.0f}" width="56" height="{hc:.0f}" rx="6"/>'
                 f'<text class="v" x="{xc + 28:.0f}" y="{Y0 - hc - 10:.0f}" text-anchor="middle">{fmt(c)}</text>')
        snap += (f'<rect class="snap" x="{xs:.0f}" y="{Y0 - hs:.0f}" width="56" height="{max(hs, 3):.0f}" rx="4"/>'
                 f'<text class="vg" x="{xs + 28:.0f}" y="{Y0 - hs - 10:.0f}" text-anchor="middle">{fmt(s)}</text>')
        cx = gx + gw / 2
        labels += f'<text class="tp" x="{cx:.0f}" y="468" text-anchor="middle">{tp}</text>'
        for k, ln in enumerate(name):
            labels += f'<text class="n" x="{cx:.0f}" y="{494 + k * 23}" text-anchor="middle">{ln}</text>'
        labels += f'<text x="{cx:.0f}" y="{494 + len(name) * 23 + 1}" text-anchor="middle">{w} weights</text>'
    chart = ('<svg class="bm" viewBox="0 0 1680 560" aria-hidden="true">'
             f'{grid}<line class="ax" x1="{X0}" y1="{Y0}" x2="{X1}" y2="{Y0}"/>'
             f'<text x="{X0 - 14}" y="{Y0 + 6}" text-anchor="end">0</text>'
             '<text x="30" y="240" text-anchor="middle" transform="rotate(-90 30 240)">seconds</text>'
             '<rect class="cold" x="120" y="8" width="20" height="20" rx="4"/><text class="lg" x="150" y="25">Cold start</text>'
             '<rect class="snap" x="290" y="8" width="20" height="20" rx="4"/><text class="lg" x="320" y="25">Snapshot restore</text>'
             f'<g data-s="1">{cold}</g><g data-s="2">{snap}</g>{labels}</svg>')
    banner = ('<div class="banner" style="left:0;top:580px;width:1680px;height:100px" data-s="2">'
              '<span>Snapshot brings each replica up in <b>3.6 to 42.7 seconds</b>, for weights from 1.5 GB to 913 GB, where a cold start takes '
              'a minute and a half to sixteen minutes.'
              '<small>Restore clock: restore request to serving. Cold-start clock: process launch to engine initialization. Neither includes image pull or container start.</small></span></div>')
    return slide(
        'Snapshot benchmark',
        kick('3.3', 'Snapshot'),
        'Cold start versus Snapshot restore, SGLang',
        chart + banner, steps=2,
        foot='SGLang on B200 with VAST storage, from the Snapshot blog draft (figure 3). Their configurations, not Super VL.',
        notes=(
            '<p>One representative figure from the Snapshot blog draft (read November 3) rather than its full benchmark matrix: SGLang, '
            'eight model and parallelism configurations on B200 with VAST storage. Restores took 3.6 to 42.7 seconds; the matching cold '
            'starts took 87 to 953 seconds.</p>'
            '<table><tr><th>Model</th><th>Parallelism</th><th>Weights</th><th>Cold start</th><th>Snapshot</th></tr>'
            + ''.join(f'<tr><td>{" ".join(n)}</td><td>{tp}</td><td>{w}</td><td>{fmt(c)} s</td><td>{fmt(s)} s</td></tr>' for n, tp, w, c, s in BENCH)
            + '</table>'
            '<p>Preserve the labels: the cold-start clock runs from process launch to engine initialization, the restore clock from the '
            'restore request to serving, and both exclude image pull and container-runtime setup. Do not call this fault-to-recovered-service '
            'time or a Super VL result. The draft&#8217;s inference benchmarks release the KV cache before checkpointing, so this is '
            'restoration of the initialized engine, not of an in-flight stream or the prefix cache.</p>'
            '<p class="dw-dim">The workshop&#8217;s own same-node Super VL TP2 control measured about 37 s agent restore and 40 to 41 s '
            'Pod-to-Ready from pre-staged NVMe (October 22), with a development build; requalify before using it as a live-demo claim.</p>'))


# ----------------------------------------------------------------------------- ModelExpress (outline 2.2)
def m1_mx_demo():
    def replica(x, cls, who, h3, tile, chip):
        tiles = ''.join(f'<div class="gt{tile[0]}"><b>TP{r}</b><span>{tile[1]}</span></div>' for r in (0, 1))
        return node(x, 0, 520, 290, f'<h3><small>{who}</small>{h3}</h3>{tiles}<span class="chip">{esc(chip)}</span>', cls=cls)
    topo = (MARKERS
            + overlay(arrow(528, 126, 1150, 126, cls='g thick', head='fund-ah-g'),
                      arrow(528, 186, 1150, 186, cls='g thick', head='fund-ah-g'))
            + replica(0, 'g', 'Replica 1 · node A', 'Serving since section 1', ('', '39 GB of weights in HBM'), 'Service: mx-source')
            + replica(1160, 'c', 'Replica 2 · node B', 'Starting now', (' e', 'empty, waiting for weights'), 'same model and settings')
            + label(540, 14, 600, '<b>&#9312; find</b> who has these weights<small>replica 1&#8217;s Service answers · metadata only</small>')
            + label(540, 218, 600, '<b>&#9313; pull</b> rank to rank, GPU to GPU<small>NIXL · LIBFABRIC over EFA · seconds per GPU</small>'))
    steps = [
        ('1', 'The one change', 'Both replicas run the ModelExpress loader. Replica 1 read storage once and now <b>publishes</b> its weights.',
         '--load-format modelexpress'),
        ('2', 'Start replica 2', 'About four minutes to Ready. <b>Back to the slides</b> while it loads; the phase pane keeps counting.',
         'kubectl apply -f peer.yaml'),
        ('3', 'Follow the transfer', 'Both TP ranks received their weights over <b>LIBFABRIC/EFA</b>, with no fallback to storage.',
         'Transfer complete ×2'),
        ('4', 'Use replica 2', 'One coding request through <b>its own frontend</b>, so it provably reaches the new worker.',
         'POST /v1/chat/completions'),
    ]
    cards = ''.join(f'<div class="card"><span class="num">{n}</span><div><h3>{h}</h3><p>{p}</p><span class="chip">{esc(c)}</span></div></div>'
                    for n, h, p, c in steps)
    return slide(
        'Demo: add a replica from a peer',
        kick('2.2', 'Demo'),
        'Demo: add a replica from a peer',
        topo + f'<div class="demo c4" style="position:absolute;left:0;top:330px;width:1680px">{cards}</div>',
        sub='Steps 1 and 2 now, then back to the slides while replica 2 starts. Steps 3 and 4 after the measured results.',
        foot='Replica 2 runs as its own small graph with its own frontend; in production you would change replicas instead. '
             'Eager profile, as in section 1.',
        notes=(
            '<p>Presenter implementation: the ModelExpress terminal demo (<code>uv run python -m demos modelexpress</code>), after '
            '<code>modelexpress prepare</code> offstage. Replica 1 is the section 1 server: it started with the ModelExpress loader, read '
            'the checkpoint from EFS and now publishes its weights. Nothing restarts it.</p>'
            '<p><b>Choreography.</b> Steps 1 and 2 here: show the settings, apply. Replica 2 needs about four minutes, so go back to the '
            'slides for the mechanism, NIXL and the measured results (about five minutes of talk), then return for steps 3 and 4. If it '
            'is not Ready yet, the phase pane shows where it is.</p>'
            '<p><b>Step 1 settings.</b> <code>--load-format modelexpress</code> plus four variables: <code>MX_METADATA_BACKEND=k8s-service</code> '
            'and <code>MX_K8S_SERVICE_PATTERN=mx-source</code> (discovery through replica 1&#8217;s Kubernetes Service, no ModelExpress '
            'server), <code>MX_NIXL_BACKEND=LIBFABRIC</code> (EFA), <code>MX_ARTIFACT_TRANSFER=0</code> (weights only; the compile caches '
            'are on the results slide, not in this demo).</p>'
            '<p><b>Last live run</b> (the November 8 recording): Ready <b>493 s</b> from storage for replica 1 against <b>248 s</b> for '
            'replica 2 (1.99&#215;). Model loading 291 &#8594; 53 s; engine init 84 &#8594; 83 s, unchanged because the eager profile has '
            'no compile step. Copies: 39.22 GB per rank in 4.2 s and 3.2 s over EFA. Replica 2 reached Ready in 247 to 250 s on all '
            'three live runs.</p>'
            '<p class="dw-dim">In all three live runs about 38 s passes between <code>Trying strategy: rdma</code> and <code>Backend '
            'LIBFABRIC was instantiated</code>: most of the peer model-loading time is transfer setup, not bytes. Not measured: any effect '
            'on a source that is serving traffic (the source was idle). Only a compatible source qualifies: same model, TP size and tensor '
            'layout. Fallback: the November 8 recording of this exact flow, demos/transcripts/live/02-modelexpress/20261108-a1/main.txt.</p>'))


# Matched startup benchmark, compiled profile, November 4: reports/workshop-measurements-20261030/startup-optimization/
# MATCHED_BASELINE_RESULTS.md. The bars use the outer timers only; the nested ones (peer copy, torch.compile, warm-up) are in the notes.
MX_ARMS = [  # label, how the weights arrive, deployment to Ready s, model loading s (slower rank), engine initialization s
    ('MX off', 'weights from EFS', 492.79, 267.39, 143.90),
    ('ModelExpress', 'weights from a peer', 280.10, 52.57, 149.12),
    ('ModelExpress', '+ compile caches', 173.61, 48.66, 40.53),
]


def m2_mx_startup():
    base = MX_ARMS[0][2]
    pxs = 1150 / base                        # px per second; the storage bar leaves room for its total
    rows = ''
    for k, (name, how, ready, load, init) in enumerate(MX_ARMS):
        segs = ''.join(f'<span class="{c}" style="width:{v * pxs:.0f}px">{v:.0f} s</span>'
                       for c, v in (('o', ready - load - init), ('w', load), ('i', init)))
        m, s = divmod(round(ready), 60)
        tot = (f'<b>{ready:.0f} s</b><small>{m} min {s} s to Ready</small>' if k == 0 else
               f'<b class="g">{ready:.0f} s</b><small>{m} min {s} s · {base / ready:.2f}&#215; faster</small>')
        st = f' data-s="{2 * k - 1}"' if k else ''       # peer weights at step 1, compile caches at step 3
        rows += (f'<div class="mxr" style="top:{48 + 106 * k}px"{st}><div class="lb"><b>{name}</b><small>{how}</small></div>'
                 f'<div class="bar">{segs}</div><div class="tot">{tot}</div></div>')
    legend = ('<div class="legend" style="position:absolute;left:290px;top:0;margin:0">'
              '<span><i class="inst"></i>Everything else</span><span><i class="ctx"></i>Model loading</span>'
              '<span><i class="tool"></i>Engine initialization</span></div>')
    cards = ('<div class="cards c3 mxc" style="top:390px">'
             + card('g', 'Model loading: 267 &#8594; 53 s',
                    '<p>The copy itself took at most <b>3.2 s</b> per GPU over EFA. The rest is setup inside the new process.</p>',
                    tag='peer weights', s=1)
             + card('a', 'Engine init: 149 s',
                    '<p>Now the biggest block. Compiling, profiling and warm&#8209;up run again on every new replica; peer weights do not '
                    'touch them.</p>', tag='still there', s=2)
             + card('g', 'Engine init: 149 &#8594; 41 s',
                    '<p>MX can also copy the compile, kernel and autotune caches: torch.compile <b>31 &#8594; 0.2 s</b>, warm&#8209;up '
                    '<b>82 &#8594; 29 s</b>. Skipping initialization entirely is Snapshot, later.</p>', tag='compile caches', s=3)
             + '</div>')
    return slide(
        'ModelExpress startup, measured',
        kick('2.2', 'ModelExpress'),
        'Eight minutes to under three',
        legend + rows + cards, steps=3,
        sub='The same replica three ways: weights from storage, from a peer, and from a peer plus its compile caches.',
        foot='Matched benchmark, compiled profile: Super VL TP2 on the same two H100s for every arm, weights over NIXL LIBFABRIC/EFA '
             'from an idle peer. One run per arm, five-second Ready polling. The live demo uses the eager profile.',
        notes=(
            '<p>The matched startup benchmark from outline 2.2, drawn as the same bar as the startup timeline. Read it top to bottom: '
            'peer weights shrink model loading, engine initialization becomes the biggest block, and the compile caches shrink that '
            'too.</p>'
            '<table><tr><th></th><th>EFS storage</th><th>Peer weights</th><th>+ compile caches</th></tr>'
            '<tr><td>Deployment to observed Ready</td><td>492.79 s</td><td>280.10 s</td><td>173.61 s</td></tr>'
            '<tr><td>Model loading, slower rank</td><td>267.39 s</td><td>52.57 s</td><td>48.66 s</td></tr>'
            '<tr><td>&#160;&#160;peer copy, slower rank</td><td>&#8212;</td><td>3.23 s</td><td>3.22 s</td></tr>'
            '<tr><td>Engine initialization</td><td>143.90 s</td><td>149.12 s</td><td>40.53 s</td></tr>'
            '<tr><td>&#160;&#160;torch.compile</td><td>26.38 s</td><td>30.76 s</td><td>0.20 s</td></tr>'
            '<tr><td>&#160;&#160;profiling and warm-up</td><td>80.72 s</td><td>82.17 s</td><td>28.51 s</td></tr></table>'
            '<p>&#8220;Everything else&#8221; on the bars is the remainder: Ready minus model loading minus engine initialization '
            '(scheduling, image, process start, the readiness tail). Indented rows are nested timers; do not add them. Peer weights: '
            '1.76&#215;, 213 s saved. With the compile caches: 2.84&#215;, 319 s (64.8%) saved.</p>'
            '<p>The compile caches are files (compiler, kernel and autotune caches) copied into the new worker before its engine needs '
            'them. Graph capture and KV allocation still run, and no running process is restored: that is Snapshot, in resiliency.</p>'
            '<p class="dw-dim">Conditions: compiled benchmark profile, text-only Super VL 120B NVFP4 at TP2; every arm on the same two '
            'H100s with fresh private caches, fixed order, one run each, five-second Ready polling, host page cache not flushed. One idle '
            'source served both MX arms; its own storage start took 512 s, so the saving needs a compatible replica already running. The '
            'live demo is the eager profile (no compile step, so its engine init stays about 83 s); its three live runs reached Ready in '
            '247 to 250 s, against 459 to 493 s from storage. '
            'The upstream deck&#8217;s &#8220;P2P alone saves 6%&#8221; was a B200 reading NFS at 22 GiB/s, where weights were already '
            'fast: the saving depends on how slow the storage path is. Source: '
            'reports/workshop-measurements-20261030/startup-optimization/MATCHED_BASELINE_RESULTS.md.</p>'))


# ----------------------------------------------------------------------------- Router (outline 2.3)
# Synthetic coding-agent load, minutes 3 to 9 of each run (reports/workshop-measurements-20261030/synthetic-scaleout/RESULTS.md)
RT_ROWS = [  # name, detail, bar class, p90 turn latency s
    ('One worker', '64 agents · 2 GPUs', 'o', 33.4),
    ('One worker', '128 agents · 2 GPUs', 'o', 140.2),
    ('Two, round-robin', '128 agents · 4 GPUs', 'a', 113.0),
    ('Two, KV routing', '128 agents · 4 GPUs', 'g', 53.8),
]


def r1_capacity():
    pxs = 1060 / max(row[3] for row in RT_ROWS)
    rows = ''
    for k, (name, detail, cls, p90) in enumerate(RT_ROWS):
        st = f' data-s="{k}"' if k else ''
        rows += (f'<div class="rt" style="top:{36 + 76 * k}px"{st}><div class="lb"><b>{name}</b><small>{detail}</small></div>'
                 f'<div class="bar {cls}" style="width:{p90 * pxs:.0f}px"></div>'
                 f'<div class="tot"><b class="{cls}">{p90:.0f} s</b></div></div>')
    legend = '<div class="rtlg"><b>p90 turn latency</b> · request to last token</div>'
    cards = ('<div class="cards c3 mxc" style="top:352px">'
             + card('r', 'Twice the agents, one worker',
                    '<p>p90: <b>33 &#8594; 140 s</b>. Turns queue behind each other&#8217;s prefills, and the agents '
                    'get 56% of the turns they ask for.</p>', tag='past its limit', s=1)
             + card('a', 'Round-robin: 113 s',
                    '<p>Splits requests evenly, not work. One worker fell behind (<b>61</b> running against <b>41</b>), and '
                    '<b>46%</b> of turns missed some of their context.</p>', tag='second worker', s=2)
             + card('g', 'KV routing: 54 s',
                    '<p>Weighs cache overlap against load: workers even (<b>55</b> and <b>55</b>), <b>87%</b> of turns where '
                    'their context was, <b>35%</b> more turns done.</p>', tag='cache-aware', s=3)
             + '</div>')
    agentx = ('<div class="banner tight" style="left:0;top:578px;width:1680px" data-s="4"><span><b>Real AgentX traces, C32:</b> '
              'round-robin let one worker queue up to 52 requests while the other held 7; KV routing kept queues at 3 or fewer.'
              '<small>p95 time to first token: one worker 2.0 s · round-robin 11.5 s · KV 2.8 s. '
              'p90 turn latency: 44 s · 35 s · 29 s.</small></span></div>')
    return slide(
        'Why didn’t more capacity help?',
        kick('2.3', 'Cache-aware routing'),
        'Why didn&#8217;t more capacity help?',
        legend + rows + cards + agentx, steps=4,
        sub='Coding agents with 12-turn sessions, about 80K-token prompts and a new turn every 45 s.',
        foot='Bars and cards: synthetic AIPerf load, not AgentX · Super VL TP2 on H100s · one run each · turns started in '
             'minutes 3 to 9.',
        notes=(
            '<p>Outline 2.3 asks why more capacity did not improve the whole request experience. This is the measured answer, and '
            'it sets up the rest of the section: what the router knows about each worker&#8217;s cache, and how it weighs that '
            'against load.</p>'
            '<ul><li>One worker at 64 agents: the slowest tenth of turns take 33 s (median 30 s). Double the agents on the same '
            'worker and they take 140 s (median 68 s); the worker serves only 56% of what the agents ask for.</li>'
            '<li>A second worker behind round-robin: the median turn drops to 45 s, but the slowest tenth still take 113 s. '
            'Round-robin splits requests evenly, not work: one worker averaged 61 running requests and the other 41, with twice '
            'the engine queue time, and 46% of turns ran on a worker missing some or all of their previous context (18% all of '
            'it).</li>'
            '<li>The same two workers behind KV routing: median 46 s, slowest tenth 54 s, and 35% more turns completed than '
            'round-robin. The workers stayed even (55 and 55 running) and 87% of turns ran where their context was.</li></ul>'
            '<table><tr><th></th><th>1 worker, 64</th><th>1 worker, 128</th><th>2, round-robin, 128</th><th>2, KV, 128</th></tr>'
            '<tr><td>Turn latency p50 / p90 / p99</td><td>30 / 33 / 36 s</td><td>68 / 140 / 169 s</td><td>45 / 113 / 128 s</td>'
            '<td>46 / 54 / 58 s</td></tr>'
            '<tr><td>TTFT p90</td><td>1.5 s</td><td>49 s</td><td>7.9 s</td><td>4.4 s</td></tr>'
            '<tr><td>Decode tok/s per user, p10 / mean</td><td>19.9 / 22.5</td><td>5.1 / 9.3</td><td>6.8 / 19.7</td>'
            '<td>12.5 / 16.0</td></tr>'
            '<tr><td>Turns completed, minutes 3 to 9</td><td>528</td><td>575</td><td>727</td><td>978</td></tr>'
            '<tr><td>Share of the requested turn rate</td><td>103%</td><td>56%</td><td>71%</td><td>96%</td></tr></table>'
            '<p>Both routers give the same median; the difference is the tail and the work done. Mean decode speed per user favors '
            'round-robin because it admitted fewer turns, so fewer shared each decode batch; it leaves out queueing and the first '
            'token, so do not present it as the routing comparison. Which round-robin worker falls behind is not predictable, so '
            'the tail gap will vary between runs.</p>'
            '<p class="dw-dim">Synthetic AIPerf user-centric load, never AgentX: 32K shared system prompt, 24K per-agent context, '
            '4K new tokens and 650 forced output tokens per turn. One run per cell; the one-worker 128-agent cell ran in a '
            'separate deployment of the same manifest (the 64-agent bridge matched within 1%). The 64-agent round-robin cell is '
            'left out: its fixed 45 s schedule pinned each agent to one worker by accident. Source: '
            'reports/workshop-measurements-20261030/synthetic-scaleout/RESULTS.md.</p>'
            '<p>Step 4, real AgentX traces at C32 (32 live session trees, the full 393-trace corpus, 15 minutes of admission): the '
            'same mechanism with real sessions. The first token is where routing shows; answer lengths vary, so turn latency '
            'mixes in how long each answer is.</p>'
            '<table><tr><th>AgentX C32</th><th>1 worker</th><th>2, round-robin</th><th>2, KV</th></tr>'
            '<tr><td>Output tok/s</td><td>464</td><td>500</td><td>525</td></tr>'
            '<tr><td>Decode tok/s per user, mean</td><td>61.9</td><td>91.2</td><td>87.5</td></tr>'
            '<tr><td>TTFT p50 / p95 / p99</td><td>0.30 / 2.0 / 9.5 s</td><td>0.35 / 11.5 / 30.7 s</td><td>0.34 / 2.8 / 7.1 s</td></tr>'
            '<tr><td>Turn latency p50 / p90</td><td>5.2 / 43.7 s</td><td>3.8 / 35.2 s</td><td>4.1 / 29.3 s</td></tr>'
            '<tr><td>Waiting requests, max per worker</td><td>7</td><td>7 / 52</td><td>2 / 3</td></tr>'
            '<tr><td>Server-reported cache read</td><td>93.4%</td><td>85.0%</td><td>88.9%</td></tr></table>'
            '<p class="dw-dim">The two-worker pair ran on November 5 with the 1 s health canary; the one-worker cell ran on November '
            '8 with canaries off (its first attempt was restarted by liveness during the primer) and on cp-0942 instead of '
            'cp-0198. One run each, so p99 is about six requests; the C16 cells showed the same order (TTFT p99 3.8 s, 15.4 s, '
            '5.2 s). Sources: reports/overnight-2026-11-04/routing-c32/C32-RESULTS.md and '
            'reports/workshop-measurements-20261030/agentx-c32-one-worker/RESULTS.md.</p>'))


# ----------------------------------------------------------------------------- 1.5: the AIPerf demo runs on this slide (2026-11-08)
def d1_aiperf_demo():
    steps = [
        ('1', 'Start the load', 'AIPerf drives the single replica with the coding-agent workload.'),
        ('2', 'Watch the metrics', 'Time to first token, inter-token latency, output tokens per second and request throughput.'),
        ('3', 'Read the report', 'The same metrics every later comparison uses. A 20-second run: read the layout, not the numbers.'),
    ]
    cards = ''.join(f'<div class="card"><span class="num">{n}</span><div><h3>{h}</h3><p>{p}</p></div></div>' for n, h, p in steps)
    return slide(
        'AIPerf demo',
        kick('1.5', 'Demo'),
        'AIPerf demo',
        f'<div class="demo">{cards}</div>',
        sub='Live: AIPerf against the single replica we just deployed.',
        notes=('<p>The AIPerf demo is triggered here, from the intro terminal (steps 5 and 6): the same short slice of the AgentX trace '
               'against the single replica at concurrency 1, then 8, about 30 s each. Point at the command and the report: TTFT, '
               'inter-token latency, output tokens per second and request throughput. It is a 20-second slice with '
               '<code>--unsafe-override</code> (AIPerf warns and marks it invalid), so the numbers are not a baseline.</p>'))


# ----------------------------------------------------------------------------- 2.6 -> 2.7: the break, after autoscaling (2026-11-08)
def d2_break():
    body = ('<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;text-align:center">'
            '<b style="font:800 190px/1 Inter,sans-serif;letter-spacing:-.04em;color:var(--dw-green-ink)">10 min</b>'
            '<p style="font-size:36px;line-height:1.3;color:var(--dw-dim);max-width:1200px;text-wrap:balance">Back in ten minutes with admission control, then the resiliency half of the workshop.</p>'
            '</div>')
    html = slide(
        'Break',
        kick('2.6', 'Break'),
        'Break',
        body,
        notes='<p>Ten-minute break. Next: admission control, then resiliency.</p>')
    return html.replace('<section class="slide" ', '<section class="slide" data-noagenda="" ', 1)   # shown, but not listed on the divider


SLIDES = [b1_snapshot_bench, m1_mx_demo, m2_mx_startup, r1_capacity, d1_aiperf_demo, d2_break]


def render_slides():
    return [f() for f in SLIDES]


if __name__ == '__main__':
    for i, h in enumerate(render_slides()):
        print(i, len(h))
