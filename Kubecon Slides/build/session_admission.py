"""Session-aware admission control: four slides added to the Router deck's admission-control subsection.

Router-deck markup conventions (1440x810 stage, .act3 colours, [data-enter] builds). Content follows the PyTorch blog
"Session-Aware Agentic Inference with NVIDIA Dynamo" (Oct 2026), section "Routing and admission control at the
session layer". Kept deliberately sparse: one idea per slide, large type, few words.
"""

BLOG = 'https://pytorch.org/blog/session-aware-agentic-inference-with-nvidia-dynamo/'
SRC = 'https://github.com/ai-dynamo/dynamo/tree/main/lib/router-plugins/builtin/src/thunderagent'

ACTBAR = '<div class="actbar"><span class="on"></span><span class="on"></span><span class="on"></span><span></span></div>'
EYEBROW = 'Admission control · Session-aware'

CSS = """
.sa2-lede{font-size:19px!important;max-width:70ch}
.sa2-two{display:grid;grid-template-columns:1.15fr 1fr;gap:22px;align-items:start}
.sa2-two .card h3{font-size:21px;margin-bottom:8px}
.sa2-two .card p{font-size:17px;line-height:1.45}
.sa2-hbm{display:flex;gap:6px;margin:10px 0 12px;height:54px}
.sa2-hbm i{flex:1;display:flex;align-items:center;justify-content:center;border-radius:8px;font:700 13px var(--mono);font-style:normal;background:var(--cyan-soft);border:1.5px solid var(--cyan);color:var(--cyan-ink)}
.sa2-hbm i.tool{background:var(--amber-soft);border-color:var(--amber);color:var(--amber-ink);border-style:dashed}
.sa2-hbm i.over{background:var(--red-soft);border-color:var(--red);color:var(--red-ink)}
.sa2-f{font:700 24px var(--mono);margin:6px 0 10px;color:var(--text)}
.sa2-f sub{font-size:14px}
.sa2-sm{display:grid;grid-template-columns:200px 1fr 1fr;grid-template-rows:auto 1fr 1fr;gap:12px;align-items:stretch}
.sa2-sm .hd{font:700 13px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--text-dim);align-self:end;text-align:center;padding-bottom:4px}
.sa2-sm .rh{font:700 15px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--text);display:flex;flex-direction:column;justify-content:center;gap:6px}
.sa2-sm .rh small{font:400 14px var(--sans);text-transform:none;letter-spacing:0;color:var(--text-dim)}
.sa2-sm .cell{border:2px solid var(--border2);border-radius:14px;padding:16px 18px;background:var(--surface);min-height:104px;display:flex;flex-direction:column;justify-content:center;gap:4px}
.sa2-sm .cell b{font-size:19px}
.sa2-sm .cell span{font-size:15px;color:var(--text-dim);line-height:1.4}
.sa2-sm .cell.on{border-color:var(--cyan);background:var(--cyan-soft)}
.sa2-sm .cell.hold{border-style:dashed;background:var(--surface2)}
.sa2-arrows{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:14px}
.sa2-arrows .card{padding:14px 18px}
.sa2-arrows .card b{display:block;font-size:17px;margin-bottom:4px;color:var(--cyan-ink)}
.sa2-arrows .card span{font-size:15.5px;line-height:1.45}
.sa2-f2{font:700 22px var(--mono);background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:14px 20px;display:inline-block;margin-bottom:6px}
.sa2-f2 sub{font-size:13px}
.sa-meter{position:relative;height:124px;margin:18px 0 6px;overflow:hidden}
.sa-bar{position:absolute;left:0;right:0;top:40px;height:40px;border-radius:10px;overflow:hidden;display:flex;border:1px solid var(--border2)}
.sa-bar i{display:block;height:100%}
.sa-bar i.ok{background:var(--accent-soft)}.sa-bar i.soft{background:var(--amber-soft);display:flex;align-items:center;justify-content:center;font:600 13px var(--mono);color:var(--amber-ink);white-space:nowrap}.sa-bar i.hot{background:var(--red-soft)}
.sa-mk{position:absolute;top:30px;width:3px;height:60px;background:var(--text)}
.sa-mk span{position:absolute;top:-28px;left:50%;transform:translateX(-50%);white-space:nowrap;font:600 15px var(--mono)}
.sa-mk.below span{top:auto;bottom:-26px}
.sa-lbl{position:absolute;top:96px;font:14px var(--mono);color:var(--text-dim);white-space:nowrap}
.sa2-rules{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.sa2-rules .card{padding:16px 18px}
.sa2-rules .card h3{font-size:20px;margin-bottom:6px}
.sa2-rules .card p{font-size:16px;line-height:1.45}
.sa2-rules .card.c-red h3{color:var(--red-ink)}.sa2-rules .card.c-amber h3{color:var(--amber-ink)}.sa2-rules .card.c-green h3{color:var(--accent-ink)}
.sa2-res{display:grid;grid-template-columns:1fr 1.25fr;gap:22px;align-items:stretch}
.sa2-res .card h3{font-size:21px}
.sa2-big{font-size:72px;font-weight:700;letter-spacing:-.03em;line-height:1;color:var(--accent-ink);margin:10px 0 6px}
.sa2-setup{font:14px var(--mono);color:var(--text-dim);line-height:1.5}
.sa2-res p{font-size:16.5px}
.sa2-bands{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0 10px}
.sa2-band{border-radius:12px;padding:14px 14px 12px;border:1.5px solid var(--border2);background:var(--surface2)}
.sa2-band small{display:block;font:600 13px var(--mono);color:var(--text-dim);margin-bottom:6px}
.sa2-band b{display:block;font-size:22px;line-height:1.15}
.sa2-band span{display:block;font-size:14px;color:var(--text-dim);margin-top:4px}
.sa2-band.up{border-color:var(--accent);background:var(--accent-soft)}.sa2-band.up b{color:var(--accent-ink)}
.sa2-band.down b{color:var(--red-ink)}
"""


def eyebrow(step, extra=''):
    return f'<div class="eyebrow" data-enter style="--i:0">{EYEBROW} <span class="step">{step}/4</span>{extra}</div>'


SLIDE_1 = f'''<section data-next="Admit and pause whole sessions" class="slide act3" data-title="Request-level routing" data-act="3">
  {ACTBAR}
  {eyebrow(1)}
  <h2 data-enter style="--i:1">A request-level router can&rsquo;t see the agent behind the request</h2>
  <p class="lede sa2-lede" data-enter style="--i:2">Dynamo&rsquo;s stock KvRouter places one request at a time: which worker has the most cache overlap. The right unit for a chat turn, the wrong unit for an agent at high concurrency.</p>
  <div class="sa2-two" data-enter style="--i:3">
    <div class="card c-cyan">
      <h3>Between turns, the cache stays put</h3>
      <div class="sa2-hbm"><i>agent 1</i><i class="tool">2 · tool</i><i>3</i><i class="tool">4 · tool</i><i>5</i><i class="tool">6 · tool</i><i>7</i><i class="tool">8 · tool</i><i class="over">no room</i></div>
      <div class="sa2-f">working set = N &times; context<sub>k</sub></div>
      <p>While an agent runs a tool, its KV sits in HBM holding blocks. The router only ever sees one turn&rsquo;s context; it has no notion of the aggregate.</p>
    </div>
    <div class="stack">
      <div class="card c-red"><h3>Cache-occupancy blowup</h3><p>Once N &times; context outgrows HBM, then DRAM, the engine evicts live sessions&rsquo; cache, and every next turn pays a full re-prefill instead of a hit.</p></div>
      <div class="card c-amber"><h3>No tool-boundary backpressure</h3><p>Over capacity, the only levers are to cancel or queue in-flight requests. Deferring a session right before its next turn, when it is about to be idle anyway, is cheaper than either.</p></div>
    </div>
  </div>
</section>'''

SLIDE_2 = f'''<section data-next="One number per worker" class="slide act3" data-title="Session-aware admission control" data-act="3">
  {ACTBAR}
  {eyebrow(2)}
  <h2 data-enter style="--i:1">Admit and pause whole sessions, at tool boundaries</h2>
  <p class="lede sa2-lede" data-enter style="--i:2">The ThunderAgent scheduler (Kang et al., 2026), ported onto Dynamo&rsquo;s KV-aware router as a native Rust plugin. One <b>program</b> per session id, weighed by its real prompt and completion tokens.</p>
  <div class="sa2-sm" data-enter style="--i:3">
    <div></div><div class="hd">active</div><div class="hd">paused</div>
    <div class="rh">reasoning<small>a turn is in flight</small></div>
    <div class="cell on"><b>Generating</b><span>The engine is working on this program&rsquo;s turn.</span></div>
    <div class="cell hold"><b>Marked to pause</b><span>Finishes the turn, then stops at the tool boundary.</span></div>
    <div class="rh">acting<small>between turns, running a tool</small></div>
    <div class="cell on"><b>Parked, KV warm</b><span>Its blocks stay on the worker for the next turn.</span></div>
    <div class="cell hold"><b>Paused</b><span>Its KV blocks may be evicted. Resumes when there is room.</span></div>
  </div>
  <div class="sa2-arrows" data-enter style="--i:4">
    <div class="card"><b>Tool boundary &rarr; acting</b><span>The natural pause point: the agent is about to be idle anyway.</span></div>
    <div class="card"><b>Memory pressure &rarr; pause</b><span>Logical only. No decode preemption: the in-flight turn finishes, which frees the engine to evict that KV. Nothing acting left? Mark the smallest reasoning program instead.</span></div>
    <div class="card"><b>Headroom &rarr; resume</b><span>Smallest paused programs first, bin-packed back under the threshold.</span></div>
  </div>
</section>'''

SLIDE_3 = f'''<section data-next="What it does to throughput" class="slide act3" data-title="The control loop" data-act="3">
  {ACTBAR}
  {eyebrow(3)}
  <h2 data-enter style="--i:1">One number per worker drives pause and resume</h2>
  <div data-enter style="--i:2"><span class="sa2-f2">U<sub>worker</sub> = &Sigma; tokens of ACTING programs on the worker &nbsp;&divide;&nbsp; KV pool capacity</span></div>
  <div class="sa-meter" data-enter style="--i:3">
    <div class="sa-bar"><i class="ok" style="width:33.3%"></i><i class="soft" style="width:50%">soft-demote band: &minus;2.0 priority, nothing paused yet</i><i class="hot" style="width:16.7%"></i></div>
    <div class="sa-mk" style="left:33.3%"><span>0.80 · pause target</span></div>
    <div class="sa-mk below" style="left:50%"><span>0.85 · resume allowed below here</span></div>
    <div class="sa-mk" style="left:83.3%"><span>0.95 · pause threshold</span></div>
    <div class="sa-lbl" style="left:0">U = 0.70</div>
    <div class="sa-lbl" style="right:0">1.00</div>
  </div>
  <div class="sa2-rules" data-enter style="--i:4">
    <div class="card c-red"><h3>U &ge; 0.95: pause</h3><p>Over-subscribed. Pause the smallest ACTING programs first, until U is back at 0.80.</p></div>
    <div class="card c-amber"><h3>0.80 to 0.95: lean on it</h3><p>Nothing paused yet. Programs take a &minus;2.0 priority penalty as early back-pressure.</p></div>
    <div class="card c-green"><h3>U &le; 0.85: resume</h3><p>Only 0.10 below the pause line, so the loop does not flap at the threshold.</p></div>
  </div>
  <div class="gx-warn" data-enter style="--i:5"><b>Resume is a bin-packing pass:</b> smallest programs first, under the threshold, with a per-program buffer. Resumed turns get a one-second priority boost, and a 30-minute cap means nothing starves.</div>
</section>'''

SLIDE_4 = f'''<section class="slide act3" data-title="Results" data-act="3">
  {ACTBAR}
  {eyebrow(4)}
  <h2 data-enter style="--i:1">Where it pays: medium and high concurrency</h2>
  <p class="lede sa2-lede" data-enter style="--i:2">At low concurrency nothing needs to pause, so it matches plain KV routing. The gain appears as concurrency grows, and it is the re-prefill work that request-level routing cannot avoid.</p>
  <div class="sa2-res" data-enter style="--i:3">
    <div class="card c-green">
      <h3>SWE-bench</h3>
      <div class="sa2-big">+12&ndash;16%</div>
      <p>throughput over KV-aware routing alone.</p>
      <div class="sa2-setup">MiniMax-M2 · two TP4 replicas · one 8&times;H100 node</div>
    </div>
    <div class="card c-cyan">
      <h3>Agentic RL rollouts</h3>
      <div class="sa2-bands">
        <div class="sa2-band"><small>CC 32&ndash;128</small><b>About even</b><span>nothing needed to pause</span></div>
        <div class="sa2-band up"><small>CC 192&ndash;256</small><b>+11.0 to 14.6%</b><span>model-token throughput</span></div>
        <div class="sa2-band up"><small>CC 384&ndash;512</small><b>Keeps scaling</b><span>while Global LB drops sharply</span></div>
      </div>
      <p>Prefix-cache hit rate above <b>94.5%</b> across the whole sweep.</p>
      <div class="sa2-setup">Uni-Agent SWE-Bench · Qwen3-Coder-30B-A3B-Instruct · 8&times;H20-3e · vs VERL&rsquo;s default Global LB</div>
    </div>
  </div>
</section>'''

SLIDES = [SLIDE_1, SLIDE_2, SLIDE_3, SLIDE_4]

NOTES = {
    'Request-level routing': (
        '<p><b>The problem with request-level routing</b> (PyTorch blog, Oct 2026). A request-level router, Dynamo&rsquo;s stock KvRouter '
        'included, solves placement one request at a time: given a prompt, which worker has the most cache overlap. That is the right unit '
        'for a single turn but the wrong unit for an agent, and at high concurrency it misses two things.</p>'
        '<ul><li><b>Cache-occupancy blowup.</b> Between turns an agent&rsquo;s cache is not freed; it sits in HBM holding blocks while the agent '
        'runs a tool. With N agents at step k the aggregate working set is N &times; context<sub>k</sub>, and the router has no notion of that '
        'aggregate. Once it exceeds HBM, then DRAM, the engine evicts live sessions&rsquo; cache and every next turn pays a full re-prefill.</li>'
        '<li><b>No tool-boundary backpressure.</b> When a worker is over capacity, a request-level router can only cancel or queue in-flight '
        'requests. Both are worse than deferring the session at the pause point right before its next turn, when it is about to be idle anyway.</li></ul>'
        f'<p class="dw-dim">Source: <a href="{BLOG}" target="_blank" rel="noopener">Session-Aware Agentic Inference with NVIDIA Dynamo</a>, '
        'section &ldquo;Routing and admission control at the session layer&rdquo;.</p>'),
    'Session-aware admission control': (
        '<p>Our first agent-aware routing strategy ports the scheduler from the ThunderAgent paper (Kang et al., 2026) on top of Dynamo&rsquo;s '
        'KV-aware router. Written in Rust, it owns a KvRouter directly rather than sitting in front of one as an extra proxy hop, and it tracks '
        f'real prompt_tokens + completion_tokens off each response. It is a native plugin: take the <a href="{SRC}" target="_blank" '
        'rel="noopener">source</a> and adapt it to your workload shape without changing the router.</p>'
        '<p>The scheduler groups requests by program_id (the session id) and moves each program through two independent states: '
        '(REASONING | ACTING) &times; (ACTIVE | PAUSED). A program enters ACTING at a tool boundary. Under memory pressure the scheduler pauses '
        'ACTING programs logically: there is no decode preemption, the in-flight turn is allowed to finish, which frees the engine to evict '
        'their KV blocks. If a worker has no ACTING programs left to pause, it marks the smallest REASONING program for pause at its next tool '
        'boundary. When a worker has headroom again, the scheduler resumes the smallest-token paused programs first, bin-packing them back under '
        'threshold.</p>'
        '<p class="dw-dim">Session identity comes from the harness headers Dynamo already recognises (Claude Code, Codex, OpenCode) or from '
        'X-Dynamo-Session-ID; subagents carry a parent id.</p>'),
    'The control loop': (
        '<p>Pause and resume are both driven off one quantity per worker: utilization, the fraction of a worker&rsquo;s KV pool occupied by its '
        'assigned programs&rsquo; working sets: U<sub>worker</sub> = (sum of token weights for ACTING programs on the worker) / (KV pool capacity).</p>'
        '<ul><li>U &ge; 0.95 (pause-threshold): over-subscribed. The tick pauses the smallest ACTING programs first until U falls back to 0.80 '
        '(pause-target).</li>'
        '<li>0.80 &le; U &lt; 0.95 (soft-demote band): not paused yet, but a &minus;2.0 priority penalty as early backpressure before a hard pause.</li>'
        '<li>Resume only fires once U &le; 0.85: pause-threshold minus a 0.10 resume-hysteresis, so the loop does not flap at the threshold.</li></ul>'
        '<p>Resume is a bin-packing pass: paused programs sorted by token count ascending, admitted smallest-first until the next one would push '
        'utilization back over threshold, accounting for a fixed per-program buffer. Resumed requests get a one-second priority boost so they do '
        'not get stuck behind fresh admissions, and a 30-minute forced-resume cap guarantees no program starves indefinitely.</p>'),
    'Results': (
        '<p>At moderate to high concurrency the difference shows up directly in throughput. On SWE-bench, running two TP4 MiniMax-M2 replicas on '
        'a single 8&times;H100 node, program-aware scheduling improved throughput roughly 12&ndash;16% over KV routing alone, the gap being the '
        're-prefill work that request-level routing cannot avoid.</p>'
        '<p>Agentic RL rollouts: Uni-Agent SWE-Bench on 8&times;H20-3e with Qwen3-Coder-30B-A3B-Instruct against VERL&rsquo;s default Global LB. '
        'Roughly even at low concurrency (CC32&ndash;128), where nothing needed to pause; 11.0&ndash;14.6% higher model-token throughput at medium '
        'concurrency (CC192&ndash;256); at high concurrency (CC384&ndash;512) Global LB throughput dropped sharply while this strategy kept scaling. '
        'Across the full sweep it held the prefix-cache hit rate above 94.5%. The blog&rsquo;s figure 3 compares VERL Global LB, the Python '
        'ThunderAgent prototype and the native scheduler across concurrency levels.</p>'
        '<p class="dw-dim">One configuration per benchmark: measured examples, not a general speed-up figure.</p>'),
}
