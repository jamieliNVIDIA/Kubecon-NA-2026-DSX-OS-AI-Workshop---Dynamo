"""Section 1 of the Dynamo workshop deck: Inference fundamentals and baseline service.

Authored for this deck from WORKSHOP_OUTLINE.md (section 1); it is not one of the ai-dynamo.org decks.
Edit the slide functions below and re-run `python3 -I build.py` to regenerate dynamo-workshop.html.

Conventions (the deck's shared engine adapter understands these):
  <section class="slide" data-title="..." data-steps="N">   one slide with N build steps
  [data-s="k"]        appears at step k  (.on when step >= k, .now when step == k)
  [data-only="1 2"]   gets .on only at the listed steps (used for highlights)
  <aside class="notes">  speaker notes (HTML), shown in the Notes panel (N)

The stage is a fixed 1920x1080 canvas scaled to the window; diagram coordinates are in px inside the
1680x720 slide body (120px side padding, header above, 112px safe area under the control bar).
"""

CSS = r"""
:root{--f-amber:#d99a00;--f-rose:#d4537e;
  --f-green-soft:rgba(118,185,0,.16);--f-cyan-soft:rgba(62,199,224,.16);--f-amber-soft:rgba(217,154,0,.16);--f-rose-soft:rgba(212,83,126,.14);--f-dim-soft:rgba(127,127,127,.13);
  --f-green-line:rgba(118,185,0,.6);--f-cyan-line:rgba(62,199,224,.65);--f-amber-line:rgba(217,154,0,.6);--f-rose-line:rgba(212,83,126,.55);--f-box:#161d21;--f-box-ink:#e8eef0}
html.dark{--f-green-soft:rgba(118,185,0,.22);--f-cyan-soft:rgba(62,199,224,.2);--f-amber-soft:rgba(217,154,0,.2);--f-rose-soft:rgba(212,83,126,.2);--f-dim-soft:rgba(255,255,255,.08);--f-box:#1c262b}

.fstage{position:absolute;left:50%;top:50%;width:1920px;height:1080px;transform:translate(-50%,-50%) scale(var(--fs,.5));overflow:hidden;background:var(--dw-bg)}
.slide{position:absolute;inset:0;overflow:hidden;opacity:0;pointer-events:none;transition:opacity .35s ease;background:var(--dw-hero);padding:64px 120px 112px;display:flex;flex-direction:column;color:var(--dw-text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.slide.active{opacity:1;pointer-events:auto}
.notes{display:none}
.hd{flex:none;display:flex;flex-direction:column;gap:14px;margin-bottom:34px}
.kicker{font:500 18px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.18em;text-transform:uppercase;color:var(--dw-green-ink)}
.kicker em{font-style:normal;color:var(--dw-dim);margin:0 8px}
h2{font:800 62px/1.06 Inter,sans-serif;letter-spacing:-.025em;text-wrap:balance;max-width:1600px}
.sub{font-size:27px;line-height:1.35;color:var(--dw-dim);max-width:1500px;text-wrap:pretty}
.body{flex:1;position:relative;min-height:0}
.foot{flex:none;margin-top:24px;display:flex;gap:16px;align-items:flex-start;font-size:23px;line-height:1.35;color:var(--dw-dim);max-width:1680px;text-wrap:pretty}
.foot::before{content:"";flex:none;width:6px;height:1.25em;border-radius:3px;background:var(--dw-green-fill);margin-top:.08em}
.foot b{color:var(--dw-text);font-weight:600}.foot>span{min-width:0}
code{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:.9em;background:var(--f-dim-soft);padding:2px 8px;border-radius:6px}

/* build steps */
[data-s]{opacity:0;transform:translateY(14px);transition:opacity .4s ease,transform .4s ease}
[data-s].on{opacity:1;transform:none}
[data-s]:not(.on){pointer-events:none}
svg [data-s]{transform:none}
.only{display:none}.only.on{display:block}

/* cards */
.cards{display:grid;gap:24px}
.cards.c3{grid-template-columns:repeat(3,1fr)}
.cards.c2{grid-template-columns:repeat(2,1fr)}
.card{background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:18px;padding:28px 32px 30px;box-shadow:var(--dw-shadow);display:flex;flex-direction:column;gap:12px;min-width:0;transition:border-color .3s}
.card.now{border-color:var(--dw-green-fill)}
.card.g{border-top:6px solid var(--dw-green-fill)}.card.c{border-top:6px solid var(--dw-cyan)}.card.a{border-top:6px solid var(--f-amber)}.card.r{border-top:6px solid var(--f-rose)}
.card h3{font:700 31px/1.15 Inter,sans-serif;letter-spacing:-.01em}
.card p{font-size:22px;line-height:1.42;color:var(--dw-dim);text-wrap:pretty}
.card p b{color:var(--dw-text);font-weight:600}
.card ul{margin:0;padding-left:26px;font-size:22px;line-height:1.42;color:var(--dw-dim);display:flex;flex-direction:column;gap:6px}
.card li b{color:var(--dw-text);font-weight:600}
.tag{align-self:flex-start;font:600 14px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--dw-green-ink);background:var(--f-green-soft);border-radius:999px;padding:7px 12px}
.card.c .tag{color:var(--dw-cyan);background:var(--f-cyan-soft)}.card.a .tag{color:var(--f-amber);background:var(--f-amber-soft)}.card.r .tag{color:var(--f-rose);background:var(--f-rose-soft)}

/* section plan */
.plan{list-style:none;display:flex;flex-direction:column;gap:14px}
.plan li{display:grid;grid-template-columns:96px 1fr 560px 120px;align-items:center;gap:28px;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:16px;padding:20px 32px;box-shadow:var(--dw-shadow)}
.plan b{font:700 24px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-green-ink)}
.plan .t{font:600 29px/1.2 Inter,sans-serif}
.plan .f{font-size:22px;line-height:1.3;color:var(--dw-dim)}
.plan .m{font:600 24px "JetBrains Mono",ui-monospace,Menlo,monospace;text-align:right}
.plan li.sum{background:transparent;border-color:transparent;box-shadow:none;padding-top:4px;padding-bottom:0}
.plan li.sum .t{color:var(--dw-dim);font-weight:500}

/* context rows (token segments) */
.rows{display:flex;flex-direction:column;gap:18px}
.row{display:flex;align-items:center;gap:8px;height:58px}
.row .lbl{flex:none;width:190px;font:600 20px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.seg{display:inline-flex;align-items:center;justify-content:center;height:54px;border-radius:10px;font:600 19px/1 Inter,sans-serif;padding:0 14px;white-space:nowrap;border:1px solid transparent;flex:none;color:var(--dw-text)}
.seg.ctx{background:var(--f-green-soft);border-color:var(--f-green-line)}
.seg.resp{background:var(--f-cyan-soft);border-color:var(--f-cyan-line)}
.seg.tool{background:var(--f-amber-soft);border-color:var(--f-amber-line)}
.seg.inst{background:var(--f-dim-soft);border-color:var(--dw-line)}
.seg.ghost{background:transparent;border:2px dashed var(--dw-line);color:var(--dw-dim);font-weight:500}
.legend{display:flex;gap:28px;align-items:center;font-size:20px;color:var(--dw-dim);margin-top:26px}
.legend i{display:inline-block;width:22px;height:22px;border-radius:6px;vertical-align:-4px;margin-right:10px;border:1px solid transparent}
.legend .ctx{background:var(--f-green-soft);border-color:var(--f-green-line)}.legend .resp{background:var(--f-cyan-soft);border-color:var(--f-cyan-line)}.legend .tool{background:var(--f-amber-soft);border-color:var(--f-amber-line)}.legend .inst{background:var(--f-dim-soft);border-color:var(--dw-line)}
.brk{position:absolute;height:24px;border:3px solid var(--dw-green-ink);border-top:none;border-radius:0 0 12px 12px}
.brk.c{border-color:var(--dw-cyan)}
.brk-lbl{position:absolute;font-size:23px;line-height:1.35;color:var(--dw-dim);text-wrap:pretty}
.brk-lbl b{display:block;color:var(--dw-green-ink);font-weight:700;font-size:25px}.brk-lbl.c b{color:var(--dw-cyan)}

/* absolute diagrams */
.ov{position:absolute;left:0;top:0;width:1680px;height:720px;overflow:visible;pointer-events:none}
.ov path,.ov line{fill:none;stroke:var(--dw-dim);stroke-width:4;stroke-linecap:round;stroke-linejoin:round}
.ov .g{stroke:var(--dw-green-ink)}.ov .c{stroke:var(--dw-cyan)}.ov .thick{stroke-width:8}.ov .dash{stroke-dasharray:10 12}
.node{position:absolute;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:20px;box-shadow:var(--dw-shadow);padding:26px 30px;display:flex;flex-direction:column;gap:10px;transition:border-color .3s}
.node.now{border-color:var(--dw-green-fill)}
.node h3{font:700 32px/1.1 Inter,sans-serif;letter-spacing:-.01em}
.node h3 small{display:block;font:500 18px/1.2 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--dw-green-ink);margin-bottom:8px}
.node p{font-size:21px;line-height:1.4;color:var(--dw-dim);text-wrap:pretty}
.node p b{color:var(--dw-text);font-weight:600}
.node.box{background:var(--f-box);color:var(--f-box-ink);border-color:rgba(255,255,255,.12)}
.node.box h3,.node.box p{color:inherit}.node.box p{opacity:.75}.node.box h3 small{color:#9fd44a}
.node.g{border-top:6px solid var(--dw-green-fill)}.node.c{border-top:6px solid var(--dw-cyan)}.node.a{border-top:6px solid var(--f-amber)}
.chip{display:inline-flex;align-self:flex-start;align-items:center;gap:8px;font:600 17px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;background:var(--f-dim-soft);border:1px solid var(--dw-line);border-radius:999px;padding:9px 14px;color:var(--dw-text);white-space:nowrap;margin-top:6px}
.node.box .chip{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.22);color:inherit}
.alabel{position:absolute;font:600 21px/1.3 Inter,sans-serif;color:var(--dw-text);text-align:center}
.alabel small{display:block;font-weight:500;font-size:19px;color:var(--dw-dim)}
.alabel.l{text-align:left}
.num{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;border-radius:50%;background:var(--dw-green-fill);color:#0b1200;font:800 19px/1 Inter,sans-serif;margin-right:12px;vertical-align:middle;flex:none}
.frame{position:absolute;border:3px dashed var(--dw-line);border-radius:28px}
.frame span{position:absolute;left:34px;top:-18px;padding:4px 14px;background:var(--dw-bg);font:600 17px/1.4 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--dw-dim)}
.banner{position:absolute;display:flex;align-items:center;gap:22px;background:var(--dw-surface);border:1px solid var(--dw-line);border-left:8px solid var(--dw-green-fill);border-radius:18px;box-shadow:var(--dw-shadow);padding:24px 30px;font-size:25px;line-height:1.35;text-wrap:pretty}
.banner b{font-weight:700}.banner small{display:block;font-size:21px;color:var(--dw-dim);margin-top:6px}
.cost{display:flex;align-items:center;gap:14px;font:600 18px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);margin-top:8px}
.cost i{height:28px;border-radius:7px;background:var(--dw-green-fill);flex:none}
.cost i.long{background:var(--f-rose)}

/* code */
.code{font:500 20px/1.5 "JetBrains Mono",ui-monospace,Menlo,monospace;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:16px;padding:24px 28px;box-shadow:var(--dw-shadow);white-space:pre;overflow:hidden;color:var(--dw-text);tab-size:2}
.code.sm{font-size:17px}
.code .k{color:var(--dw-cyan)}.code .v{color:var(--dw-green-ink)}.code .c{color:var(--dw-dim)}.code .p{color:var(--f-amber)}
.code .ln{display:block;margin:0 -12px;padding:0 12px;border-radius:6px;transition:background .3s}
.code .ln[data-only].on{background:var(--f-green-soft)}

/* GPU memory bar */
.mem{position:absolute;left:0;top:30px;width:1680px;height:190px;display:flex;border-radius:22px;overflow:hidden;border:1px solid var(--dw-line);background:var(--dw-surface);box-shadow:var(--dw-shadow)}
.mem .m{display:flex;flex-direction:column;justify-content:flex-start;gap:6px;padding:24px 30px 0;border-right:1px solid var(--dw-line);position:relative;min-width:0}
.mem .m:last-child{border-right:none}
.mem .m h4{font:700 28px/1.1 Inter,sans-serif;white-space:nowrap}
.mem .m small{font-size:19px;color:var(--dw-dim);white-space:nowrap}
.mem .w{background:var(--f-green-soft)}.mem .e{background:var(--f-amber-soft)}.mem .kv{background:var(--f-cyan-soft)}
.pool{position:absolute;left:16px;right:16px;bottom:14px;height:56px;display:flex;gap:8px}
.pool i{display:flex;align-items:center;justify-content:center;border-radius:8px;font:600 16px "JetBrains Mono",ui-monospace,Menlo,monospace;font-style:normal;background:var(--dw-cyan);color:#06262c;flex:none}
.pool i.free{background:transparent;border:2px dashed var(--f-cyan-line);color:var(--dw-dim);flex:1}
.memcap{position:absolute;left:0;top:250px;width:1680px;display:grid;gap:24px}
.memcap p{font-size:23px;line-height:1.4;color:var(--dw-dim);text-wrap:pretty}.memcap p strong{display:block;color:var(--dw-text);font-size:25px;font-weight:700;margin-bottom:6px}.memcap p b{color:var(--dw-text);font-weight:600}

/* prefill / decode */
.pd{position:absolute;left:0;top:30px;width:1680px;height:120px;display:flex;gap:10px;align-items:stretch}
.pd .pf{width:560px;border-radius:16px;background:var(--f-green-soft);border:1px solid var(--f-green-line);display:flex;align-items:center;justify-content:center;font:700 26px Inter,sans-serif;flex:none}
.pd .tk{flex:1;border-radius:12px;background:var(--f-cyan-soft);border:1px solid var(--f-cyan-line);display:flex;align-items:center;justify-content:center;font:600 18px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.pd .tk.more{background:transparent;border:2px dashed var(--dw-line)}

/* startup timeline */
.tl{position:absolute;left:0;top:70px;width:1680px;height:130px;display:flex;border-radius:18px;overflow:hidden;border:1px solid var(--dw-line);box-shadow:var(--dw-shadow);background:var(--dw-surface)}
.tl .ph{display:flex;flex-direction:column;justify-content:center;padding:0 26px;gap:6px;border-right:3px solid var(--dw-bg);min-width:0;flex:none}
.tl .ph:last-child{border-right:none}
.tl .ph h4{font:700 26px/1.1 Inter,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tl .ph small{font:600 21px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim)}
.tl .o{background:var(--f-dim-soft)}.tl .w{background:var(--f-green-soft)}.tl .i{background:var(--f-amber-soft)}
.tick{position:absolute;top:40px;height:190px;border-left:4px solid var(--dw-text)}
.tick span{position:absolute;right:14px;top:-34px;font:700 24px "JetBrains Mono",ui-monospace,Menlo,monospace;white-space:nowrap}
.tlcap{position:absolute;left:0;top:230px;width:1680px;display:flex}
.tlcap div{padding:0 26px 0 0;flex:none}
.tlcap p{font-size:21px;line-height:1.4;color:var(--dw-dim);text-wrap:pretty}.tlcap p strong{display:block;color:var(--dw-text);font-size:23px;font-weight:700;margin-bottom:6px}.tlcap p b{color:var(--dw-text);font-weight:600}
.chips{position:absolute;left:0;top:470px;width:1680px;display:flex;flex-direction:column;gap:14px}
.chips div{display:flex;align-items:flex-start;gap:16px;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:14px;padding:16px 24px;font-size:22px;line-height:1.35;color:var(--dw-dim);box-shadow:var(--dw-shadow)}
.chips div b{color:var(--dw-text);font-weight:600}
.chips .lab{flex:none;font:600 15px/1 "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--dw-green-ink);background:var(--f-green-soft);border-radius:999px;padding:8px 12px;margin-top:4px}

/* demo cue cards */
.demo{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}
.demo .card{flex-direction:row;align-items:flex-start;gap:18px;padding:26px 28px}
.demo .card div{display:flex;flex-direction:column;gap:8px;min-width:0}
.demo .card h3{font-size:27px}
.demo .card p{font-size:20px}
.demo .card .chip{margin-top:2px;max-width:100%;overflow:hidden;text-overflow:ellipsis}

/* metrics */
.mt{position:absolute;left:0;top:212px;width:1680px;display:flex;flex-direction:column;gap:12px}
.mt .r{display:grid;grid-template-columns:600px 1fr;align-items:center;gap:30px;background:var(--dw-surface);border:1px solid var(--dw-line);border-radius:16px;padding:15px 30px;box-shadow:var(--dw-shadow)}
.mt .r .n{font:700 27px/1.15 Inter,sans-serif}
.mt .r .n small{display:block;font:500 17px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);margin-top:5px;letter-spacing:.04em}
.mt .r .q{font-size:25px;line-height:1.3;color:var(--dw-dim)}
.mt .r .q b{color:var(--dw-text);font-weight:600}
.strip{position:absolute;left:0;top:0;width:1680px;height:200px}
.strip [data-s]{opacity:.28;transition:opacity .3s}.strip [data-s].on{opacity:1}
.strip text{font-family:Inter,sans-serif;font-size:20px;font-weight:600;fill:var(--dw-text)}
.strip text.d{fill:var(--dw-dim);font-weight:500}
.strip text.m{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:18px}
.strip .ax{stroke:var(--dw-line);stroke-width:4}
.strip .tok{fill:var(--dw-cyan)}
.strip .ft{fill:var(--dw-green-fill)}
.strip .req{fill:var(--dw-text)}
.strip .br{fill:none;stroke-width:3}
.strip .br.g{stroke:var(--dw-green-ink)}.strip .br.c{stroke:var(--dw-cyan)}.strip .br.d{stroke:var(--dw-dim)}

/* interactivity versus throughput (Pareto) */
.pfc{position:absolute;left:0;top:0;width:1680px;height:410px}
.pfc text{font:500 19px Inter,sans-serif;fill:var(--dw-dim)}
.pfc text.t{font-weight:600;fill:var(--dw-text)}
.pfc text.lab{font:600 20px Inter,sans-serif;fill:var(--dw-text)}
.pfc text.tl{font:500 17px "JetBrains Mono",ui-monospace,Menlo,monospace;fill:var(--dw-cyan)}
.pfc .ax{fill:none;stroke:var(--dw-line);stroke-width:4}.pfc .tk{stroke:var(--dw-line);stroke-width:2}
.pfc .cv{fill:none;stroke:var(--dw-green-ink);stroke-width:7;stroke-linecap:round}
.pfc .tgt{stroke:var(--dw-cyan);stroke-width:3;stroke-dasharray:12 12}
.pfc .gl{stroke:var(--dw-dim);stroke-width:2;stroke-dasharray:6 8}
.pfc .dot{fill:var(--f-rose);stroke:var(--dw-surface);stroke-width:5}
.pfc .pt{fill:var(--dw-green-ink);stroke:var(--dw-surface);stroke-width:3}.pfc .pt.sel{fill:var(--f-rose)}
.pfc .ring{fill:none;stroke:var(--dw-dim);stroke-width:2;stroke-dasharray:5 5}
.pf-cards{position:absolute;left:0;top:428px;width:1680px;display:grid;grid-template-columns:1fr 1fr;gap:24px}
.pf-cards .card{padding:20px 26px 18px;gap:8px}
.pf-cards .card h3{font-size:24px}
.pf-cards .card p{font-size:18px;line-height:1.35}
.pf-cards .card p b.k{display:inline-block;min-width:112px;font:600 14px "JetBrains Mono",ui-monospace,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--dw-green-ink)}
.pf-cards .card.c p b.k{color:var(--dw-cyan)}

/* memory tiers */
.tiers{position:absolute;left:0;top:0;width:1680px;display:flex;flex-direction:column;gap:10px}
.axis{display:grid;grid-template-columns:360px 520px 1fr;gap:26px;padding:0 26px 0 36px;font:500 15px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);align-items:end}
.axis .ticks{position:relative;height:22px;width:440px}.axis .ticks span{position:absolute;bottom:0;transform:translateX(-50%);white-space:nowrap}
.tier{display:grid;grid-template-columns:360px 520px 1fr;align-items:center;gap:26px;background:var(--dw-surface);border:1px solid var(--dw-line);border-left:10px solid var(--t);border-radius:16px;padding:14px 26px;box-shadow:var(--dw-shadow);min-height:98px}
.tier.side{border-style:dashed;border-left-style:solid;background:transparent;box-shadow:none}
.tier h4{font:700 27px/1.1 Inter,sans-serif}.tier h4 small{display:block;font:500 16px/1.3 "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);margin-top:6px}
.tier .what{font-size:20px;line-height:1.35;color:var(--dw-dim);text-wrap:pretty}.tier .what b{color:var(--dw-text);font-weight:600}
.tier .cap{font:700 25px/1.1 Inter,sans-serif}.tier .cap small{display:block;font:500 16px "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);margin-top:5px}
.bw{position:relative;height:64px}
.bw .track{position:absolute;left:0;top:31px;width:440px;height:2px;background:var(--dw-line)}
.bw .bar{position:absolute;left:0;top:21px;height:22px;border-radius:0 6px 6px 0;background:var(--t)}
.bw .bar.fade{background:linear-gradient(90deg,var(--t) 55%,transparent)}
.bw .bar.b1{top:8px;height:18px}.bw .bar.b2{top:38px;height:18px;opacity:.65}
.bw .v{position:absolute;top:18px;font:700 20px/1.3 "JetBrains Mono",ui-monospace,Menlo,monospace;white-space:nowrap;color:var(--dw-text)}
.bw .v small{font-weight:500;color:var(--dw-dim);font-size:16px}
.bw .v.v1{top:4px;font-size:18px}.bw .v.v2{top:34px;font-size:18px}
.bw.tall{height:84px}.bw.tall .track{top:41px}.bw .bar.t1{top:4px;height:16px}.bw .bar.t2{top:34px;height:16px;opacity:.8}.bw .bar.t3{top:64px;height:16px;opacity:.6}
.bw .v.w1{top:0;font-size:17px}.bw .v.w2{top:30px;font-size:17px}.bw .v.w3{top:60px;font-size:17px}.bw .v.w1 small,.bw .v.w2 small,.bw .v.w3 small{font-size:14px}
.src{position:absolute;left:0;bottom:0;font:500 15px/1.3 "JetBrains Mono",ui-monospace,Menlo,monospace;color:var(--dw-dim);white-space:nowrap}
"""

JS = r"""
const __stage = __root.querySelector('.fstage');
const __fit = () => __stage.style.setProperty('--fs', Math.min(innerWidth / 1920, innerHeight / 1080));
__fit(); addEventListener('resize', __fit);
"""


# ----------------------------------------------------------------------------- helpers
def esc(t):
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def slide(title, kicker, h2, body, steps=0, sub='', foot='', notes=''):
    hd = (f'<div class="hd"><div class="kicker">{kicker}</div><h2>{h2}</h2>'
          + (f'<p class="sub">{sub}</p>' if sub else '') + '</div>')
    ft = ''   # the bottom asides were removed on 2026-11-08 at the user's request; foot= arguments are kept in the sources but not rendered
    return (f'<section class="slide" data-title="{esc(title)}" data-steps="{steps}">'
            f'{hd}<div class="body">{body}</div>{ft}'
            f'<aside class="notes">{notes}</aside></section>')


def kick(part, label):
    # outline numbers ("2.4") stopped matching the deck's sections when they were reordered (2026-11-08): label only
    return label if part.replace('.', '').isdigit() else f'{part}<em>·</em>{label}'


def node(x, y, w, h, inner, cls='', s=None):
    st = f' data-s="{s}"' if s is not None else ''
    return f'<div class="node {cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px"{st}>{inner}</div>'


def label(x, y, w, inner, cls='', s=None):
    st = f' data-s="{s}"' if s is not None else ''
    return f'<div class="alabel {cls}" style="left:{x}px;top:{y}px;width:{w}px"{st}>{inner}</div>'


def arrow(x1, y1, x2, y2, cls='', s=None, head='fund-ah', mid=None):
    """Straight (or one-bend) arrow in the 1680x720 overlay."""
    st = f' data-s="{s}"' if s is not None else ''
    d = f'M{x1} {y1} L{x2} {y2}' if mid is None else f'M{x1} {y1} Q{mid[0]} {mid[1]} {x2} {y2}'
    return f'<path class="{cls}" d="{d}" marker-end="url(#{head})"{st}/>'


def overlay(*paths):
    return '<svg class="ov" viewBox="0 0 1680 720" aria-hidden="true">' + ''.join(paths) + '</svg>'


MARKERS = ('<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
           '<marker id="fund-ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
           '<path d="M0 0 L10 5 L0 10 z" style="fill:var(--dw-dim)"/></marker>'
           '<marker id="fund-ah-g" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">'
           '<path d="M0 0 L10 5 L0 10 z" style="fill:var(--dw-green-ink)"/></marker>'
           '<marker id="fund-ah-c" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
           '<path d="M0 0 L10 5 L0 10 z" style="fill:var(--dw-cyan)"/></marker>'
           '</defs></svg>')


def seg(cls, text, w=None, s=None):
    st = f' data-s="{s}"' if s is not None else ''
    wd = f' style="width:{w}px"' if w else ''
    return f'<span class="seg {cls}"{wd}{st}>{text}</span>'


def row(lbl, segs, s=None):
    st = f' data-s="{s}"' if s is not None else ''
    return f'<div class="row"{st}><span class="lbl">{lbl}</span>{"".join(segs)}</div>'


def card(cls, h3, body, tag='', s=None):
    st = f' data-s="{s}"' if s is not None else ''
    tg = f'<span class="tag">{tag}</span>' if tag else ''
    return f'<div class="card {cls}"{st}>{tg}<h3>{h3}</h3>{body}</div>'


# ----------------------------------------------------------------------------- slides
def s00_plan():
    parts = [
        ('1.1', 'Coding-agent loop and growing context', 'Simplified visual explanation', '3 min'),
        ('1.2', 'Inside vLLM: HTTP, processing phases, and state', 'Progressive zoom into the server', '4 min'),
        ('1.3', 'Prefix reuse and the implications of retained state', 'Visual explanation; no separate live reuse experiment', '3 min'),
        ('1.4', 'Barebones DGD, operator reconciliation, resources, startup', 'Manifest walkthrough and deployment demonstration', '6 min'),
        ('1.5', 'AIPerf baseline and metrics', 'Controlled load and interpretation of results', '4 min'),
    ]
    lis = ''.join(f'<li><b>{p}</b><span class="t">{t}</span><span class="f">{f}</span><span class="m">{m}</span></li>'
                  for p, t, f, m in parts)
    lis += '<li class="sum"><b></b><span class="t">Only the concepts the later experiments need</span><span class="f"></span><span class="m">20 min</span></li>'
    return slide(
        'Twenty minutes, five parts',
        kick('Section 1', 'Inference fundamentals and baseline service'),
        'Twenty minutes, five parts',
        f'<ol class="plan">{lis}</ol>',
        sub='Start with vLLM as the server. Dynamo enters only after prefix reuse and its operational implications are on the table.',
        notes=(
            '<h4>Purpose</h4><p>Drive adoption of Dynamo by showing production inference problems that experienced Kubernetes '
            'operators may not have met yet, then investigating how Dynamo addresses them.</p>'
            '<h4>Audience and format</h4><ul><li>Solid Kubernetes and distributed-systems foundations; surface-level familiarity with '
            'inference engines such as vLLM.</li><li>Presenter-led investigation. Attendees have no individual clusters and no access to '
            'the demonstration cluster.</li><li>Take-home goal: deploy a Dynamo-managed service and reproduce the investigations.</li></ul>'
            '<h4>Motivating application</h4><p>Coding agents. The workload stays constant for the whole workshop; only offered load, '
            'serving configuration and injected failures change.</p>'
            '<h4>Timing</h4><p>20 minutes total, after the 30-minute NVKE introduction. Metrics are introduced here and used throughout; '
            'there is no separate observability section.</p>'))


def s01_agent_loop():
    body = MARKERS + overlay(
        arrow(540, 190, 1138, 190, s=1),
        arrow(540, 302, 1138, 302, cls='g thick', s=4, head='fund-ah-g'),
        arrow(1140, 390, 542, 390, cls='c', s=2, head='fund-ah-c'),
        arrow(150, 432, 150, 486, cls='dash', s=3),
        arrow(400, 486, 400, 432, cls='dash', s=3),
    )
    body += node(0, 130, 540, 300,
                 '<h3>Agent</h3>'
                 '<p>Holds the code, the user&#8217;s request and everything the session has produced so far. '
                 'Decides what to send next and runs tools.</p>')
    body += node(1140, 130, 540, 300,
                 '<h3>LLM server</h3>'
                 '<p>Accepts requests over HTTP and returns model responses.</p>'
                 '<span class="chip">POST /v1/chat/completions</span>', cls='box')
    body += label(580, 136, 520, '<span class="num">1</span>code + user request', s=1)
    body += label(545, 236, 590, '<span class="num">4</span>the whole accumulated context'
                  '<small>code + request · prior responses · tool results · new instruction</small>', s=4)
    body += label(560, 406, 560, '<span class="num">2</span>a response, which may ask for a tool call', s=2)
    body += node(0, 490, 540, 160,
                 '<h3><span class="num">3</span>Run the tool</h3>'
                 '<p>File contents, test output, an error message: more text for the context.</p>', s=3)
    body += (f'<div class="banner" style="left:640px;top:490px;width:1040px;height:160px" data-s="5">'
             f'<span class="num">5</span><div><b>Repeat until the task is complete.</b>'
             f'<small>One agent session is many inference requests, and each request carries the whole context so far.</small></div></div>')
    return slide(
        'The coding-agent loop',
        kick('1.1', 'Start with the coding agent'),
        'A coding agent is a loop around an HTTP endpoint',
        body, steps=5,
        notes=(
            '<p>Treat the LLM server as a black box behind an HTTP endpoint. Build the loop one step at a time:</p>'
            '<ol><li>A program takes code and a user request and sends them to the server.</li>'
            '<li>The server returns a response, which may request a tool call.</li>'
            '<li>The program executes the tool and obtains more text: file contents, test output, an error message.</li>'
            '<li>The program sends the accumulated context back: original code and request, prior responses, tool results, '
            'and any new instruction.</li><li>Repeat until the task is complete.</li></ol>'
            '<p><b>Make clear:</b> one agent session consists of multiple inference requests.</p>'
            '<p class="dw-dim">Intentionally simplified. Agent frameworks and context-management strategies are outside this introduction.</p>'))


def s02_growing_context():
    W = dict(code=300, resp=200, tool=170, inst=180)
    turn = [seg('resp', 'response', W['resp']), seg('tool', 'tool result', W['tool']), seg('inst', 'instruction', W['inst'])]
    rows = row('Request 1', [seg('ctx', 'code + user task', W['code'])])
    rows += row('Request 2', [seg('ctx', 'code + user task', W['code'])] + turn, s=1)
    rows += row('Request 3', [seg('ctx', 'code + user task', W['code'])] + turn + turn, s=2)
    rows += row('Request n', [seg('ghost', 'every turn appends to the context, and the whole context is sent again', 1440)], s=3)
    legend = ('<div class="legend"><span><i class="ctx"></i>original code + task</span><span><i class="resp"></i>assistant / tool-call response</span>'
              '<span><i class="tool"></i>tool result</span><span><i class="inst"></i>next instruction</span></div>')
    body = f'<div class="rows">{rows}</div>{legend}'
    return slide(
        'One session, many requests',
        kick('1.1', 'Start with the coding agent'),
        'One session, many requests, a context that keeps growing',
        body, steps=3,
        foot='Each request is a separate inference call. The agent resends the <b>entire accumulated context</b> every time; '
             'the server sees a fresh prompt.',
        notes=(
            '<p>The point of this slide is the shape of the traffic: successive requests from one session share a long, '
            'growing prefix. Everything the later sections build on (prefix reuse, routing, cache movement) starts here.</p>'
            '<p>Keep it simple: no agent framework internals, no context-window management, no compaction.</p>'))


def s03_zoom():
    body = MARKERS + overlay(arrow(530, 310, 598, 310, s=1), arrow(1080, 310, 1148, 310, s=2))
    body += '<div class="frame" style="left:0;top:40px;width:1680px;height:520px"><span>LLM server</span></div>'
    body += node(50, 120, 480, 360,
                 '<h3>HTTP endpoint</h3>'
                 '<p>Accepts prompts through the OpenAI-compatible API and streams generated tokens to the client.</p>'
                 '<span class="chip">POST /v1/chat/completions</span>', cls='g')
    body += node(600, 120, 480, 360,
                 '<h3>vLLM engine</h3>'
                 '<p>Tokenizes prompts. Schedules active sequences with <b>continuous batching</b>. Launches GPU forward passes '
                 'and allocates <b>KV-cache blocks</b>.</p>', cls='c', s=1)
    body += node(1150, 120, 480, 360,
                 '<h3>GPUs</h3>'
                 '<p><b>HBM</b> stores model weights, KV cache and activations. GPU kernels execute attention and matrix '
                 'multiplications. Performance depends on compute throughput and memory bandwidth.</p>', cls='a', s=2)
    return slide(
        'LLM serving architecture',
        kick('1.2', 'Inside the vLLM server'),
        'LLM serving architecture',
        body, steps=2,
        notes=(
            '<p>The HTTP endpoint accepts requests and streams output tokens. The first click reveals vLLM: tokenization, '
            'continuous batching, forward-pass scheduling and KV-cache allocation.</p>'
            '<p>Continuous batching lets requests join at iteration boundaries when the scheduler has capacity and KV blocks '
            'available. The second click reveals the GPUs: HBM holds the weights, KV cache and activations; kernels execute '
            'the model. Compute throughput and HBM bandwidth constrain prefill and decode differently.</p>'))


def s04_state():
    cards = card('g', 'Model weights',
                 '<p>The model&#8217;s parameters, loaded into GPU memory at startup. <b>Shared by every request</b> and independent of '
                 'whatever is being served right now.</p>', tag='per model · loaded once', s=1)
    cards += card('c', 'Request working state · the KV cache',
                  '<p>State built while processing a request&#8217;s context and generating its answer. <b>Prefill creates it; '
                  'generation uses and updates it.</b> One per active request, and it grows with the context.</p>',
                  tag='per request · grows with context', s=2)
    cards += card('a', 'Initialized engine state',
                  '<p>Startup work beyond loading weights: compilation, warm-up, communicators, captured graphs. '
                  '<b>Expensive to build</b>, which is why startup and recovery take as long as they do.</p>',
                  tag='per process · built at startup', s=3)
    return slide(
        'Three kinds of state',
        kick('1.2', 'Inside the vLLM server'),
        'The engine holds three kinds of state',
        f'<div class="cards c3">{cards}</div>', steps=3,
        foot='Working state is an abstraction on purpose: no attention mathematics, no KV tensor layouts, no recurrent-state '
             'differences. It is what the workshop needs.',
        notes=(
            '<ul><li><b>Model weights:</b> parameters that must be in memory for inference; shared across requests and independent of '
            'the particular request.</li>'
            '<li><b>Request working state / KV cache:</b> state associated with processing the context and generating an answer. '
            'Prefill processes the input and builds it; generation uses and updates it.</li>'
            '<li><b>Initialized engine state:</b> briefly acknowledge startup work beyond loading weights, such as compilation and '
            'warm-up. Its operational importance returns in the startup and recovery experiments.</li></ul>'
            '<p class="dw-dim">Do not teach attention mathematics, KV tensor layouts, or the differences between attention KV caches and '
            'recurrent/Mamba state.</p>'))


def s05_prefill_decode():
    toks = ''.join(f'<div class="tk" data-s="2">t{i}</div>' for i in range(1, 11)) + '<div class="tk more" data-s="2">…</div>'
    bar = f'<div class="pd"><div class="pf" data-s="1">prefill · process input tokens</div>{toks}</div>'
    caps = ('<div class="memcap" style="top:200px;grid-template-columns:560px 1fr;gap:60px">'
            '<p data-s="1"><strong>Prefill</strong>Processes input tokens and <b>builds the KV cache</b>. Longer prompts require more work. '
            'Prefill and queueing contribute to <b>time to first token</b>.</p>'
            '<p data-s="2"><strong>Decode</strong>Generates one token per active sequence per step, reading model weights and '
            '<b>updating the KV cache</b>. Decode step time determines <b>inter-token latency</b>.</p></div>')
    return slide(
        'Prefill, then decode',
        kick('1.2', 'Inside the vLLM server'),
        'Prefill and decode',
        bar + caps, steps=2,
        notes=(
            '<p>Prefill versus decode: enough distinction to interpret prompt-processing time and generation speed later.</p>'
            '<p>Prefill is compute-heavy and proportional to the input; decode is a sequence of small steps that read the working '
            'state. The two phases are the vocabulary for TTFT and ITL in 1.5, and for disaggregation in the scaling section.</p>'))


def s06_memory():
    pool = ('<div class="pool" data-s="4">'
            '<i style="width:140px">user A</i><i style="width:80px">user B</i><i style="width:180px">user C</i><i style="width:110px">user D</i>'
            '<i class="free">free</i></div>')
    mem = ('<div class="mem">'
           '<div class="m w" style="width:780px" data-s="1"><h4>Model weights</h4><small>the same for every request</small></div>'
           '<div class="m e" style="width:280px" data-s="2"><h4>Workspace</h4><small>buffers and graphs</small></div>'
           f'<div class="m kv" style="width:620px" data-s="3"><h4>KV cache pool</h4><small>working state of the active requests</small>{pool}</div>'
           '</div>')
    caps = ('<div class="memcap" style="grid-template-columns:780px 280px 620px;gap:0">'
            '<p data-s="1" style="padding-right:40px"><strong>Fixed, large</strong>Loaded once at startup. Nothing about the traffic changes it.</p>'
            '<p data-s="2" style="padding-right:30px"><strong>Fixed</strong>Activation buffers and scratch space.</p>'
            '<p data-s="3"><strong>What is left</strong>Cache occupies real memory. One engine serves several active requests from different users '
            'at once, and their state shares this pool.</p></div>')
    return slide(
        'GPU memory is a budget',
        kick('1.2', 'Inside the vLLM server'),
        'GPU memory is one finite budget',
        mem + caps, steps=4,
        foot='Active-request concurrency trades <b>throughput</b> against <b>per-request latency</b>.',
        notes=(
            '<p>Simple GPU-memory illustration: model weights, engine buffers/workspace, and the cache pool share a finite memory budget. '
            'Cache occupies real memory, and an engine can serve multiple active requests from different users at once.</p>'
            '<p>Develop the concurrency/performance tradeoff in the scaling opener rather than expanding this into a scheduling lesson.</p>'
            '<p class="dw-dim">Proportions are illustrative, not a measurement of the workshop model.</p>'))


def s06b_tiers():
    """Memory tiers below and beside the GPU, with figures from the NVIDIA Rubin platform post."""
    PX = 88  # px per decade on the log-scale bandwidth track: 10 GB/s at 0 .. 1 PB/s at 440
    import math
    bw = lambda tbs: round(PX * (math.log10(tbs) + 2))

    def tier(color, name, sub, what, cap, capsub, bars, s, cls='', bwcls=''):
        return (f'<div class="tier {cls}" style="--t:{color}" data-s="{s}">'
                f'<h4>{name}<small>{sub}</small></h4><p class="what">{what}</p>'
                f'<div class="bw {bwcls}"><i class="track"></i>{bars}</div></div>')

    def bar(tbs, text, small='', cls='', vcls=''):
        w = bw(tbs)
        sm = f' <small>{small}</small>' if small else ''
        return f'<i class="bar {cls}" style="width:{w}px"></i><span class="v {vcls}" style="left:{w + 12}px">{text}{sm}</span>'

    axis = ('<div class="axis"><span></span><span></span><div class="ticks">'
            '<span style="left:0">10 GB/s</span><span style="left:88px">100 GB/s</span><span style="left:176px">1 TB/s</span>'
            '<span style="left:264px">10 TB/s</span><span style="left:352px">100 TB/s</span><span style="left:440px">1 PB/s</span></div></div>')
    rows = tier('var(--dw-green-fill)', 'On-chip SRAM', 'Groq 3 LPX LPU · 40 PB/s per rack',
                '<b>Primary working storage</b> on the Groq 3 LPX: weights, activations and KV state. On a GPU: registers and caches.',
                '500 MB', 'per LPU · 128 GB per rack', bar(150, '150 TB/s', 'per LPU'), 1)
    rows += tier('var(--dw-cyan)', 'HBM4', 'stacked on the GPU package',
                 '<b>Model weights, workspace and the KV cache pool</b>: the budget from the previous slide.',
                 '288 GB', 'per Rubin GPU', bar(22, '22 TB/s'), 2)
    rows += tier('var(--f-amber)', 'CPU DRAM', 'LPDDR5X on the Vera CPU · NVLink-C2C',
                 '<b>Offloaded KV cache</b>; KVCR serves it to peer workers. NVLink-C2C makes it one pool with HBM4.',
                 '1.5 TB', 'per Vera CPU', bar(1.2, '1.2 TB/s', '· C2C 0.9 TB/s each way'), 3)
    rows += tier('var(--f-rose)', 'Offloaded memory: flash', 'local NVMe · Ethernet-attached flash (ICMS)',
                 '<b>Cold KV cache and context</b>, model files, checkpoints. Per node over PCIe, or shared by a pod over the network.',
                 'TB → PB', 'per node → per pod',
                 bar(0.128, '128 GB/s', 'PCIe Gen6 x16 · local NVMe', 't1', 'w1')
                 + bar(0.2, '200 GB/s', 'ConnectX-9 per GPU · 1.6 Tb/s', 't2', 'w2')
                 + bar(0.1, '100 GB/s', 'BlueField-4 port · 800 Gb/s', 't3', 'w3'), 4, bwcls='tall')
    rows += tier('var(--dw-dim)', 'A peer GPU&#8217;s HBM', 'sideways over NVLink 6 · a neighbor, not a tier',
                 'Prefill-to-decode handoff, peer weights (ModelExpress): <b>GPU to GPU, no trip down the ladder</b>.',
                 '72 × 288 GB', 'in one NVL72 rack', bar(1.8, '1.8 TB/s', 'each way · 3.6 both ways'), 5, cls='side')
    src = ('<p class="src">Sources: NVIDIA Rubin platform post; Groq 3 LPX post for SRAM. '
           'Log scale · memory rows: total bandwidth · link rows: one direction.</p>')
    return slide(
        'Memory tiers and bandwidth',
        kick('1.2', 'Inside the vLLM server'),
        'Memory tiers: more capacity, less bandwidth',
        f'<div class="tiers">{axis}{rows}</div>{src}', steps=5,
        foot='Each step down trades bandwidth for capacity. Where a request&#8217;s KV cache sits decides how fast the engine can reach '
             'it: <b>CPU offloading</b> (scaling), <b>peer reuse</b> (KVCR) and tiered context storage all move state along this ladder.',
        notes=(
            '<p>Builds on the budget slide: HBM is where the weights, workspace and KV cache pool live, and it is small and fast. Every '
            'tier below holds more and delivers less bandwidth; the sideways option is another GPU&#8217;s HBM over NVLink. The top rung '
            'is a different chip: the Groq 3 LPX keeps its working set in SRAM at 150 TB/s, which is why it takes the decode FFN/MoE work '
            'while Rubin GPUs do prefill and attention over the KV cache.</p>'
            '<h4>SRAM figures: Groq 3 LPX post</h4>'
            '<p><a href="https://developer.nvidia.com/blog/inside-nvidia-groq-3-lpx-the-low-latency-inference-accelerator-for-the-nvidia-vera-rubin-platform/">Inside NVIDIA Groq 3 LPX</a>: '
            '500 MB of on-chip SRAM per LPU as the primary working storage for inference, with 150 TB/s of on-chip memory bandwidth; '
            '96 C2C links at 112 Gbps, 2.5 TB/s per LPU. Per tray (16 LPUs): 8 GB SRAM, 2.4 PB/s. Per rack (256 LPUs): 128 GB SRAM, '
            '40 PB/s, 640 TB/s scale-up. The compiler and runtime place the active working set (weights, activations, KV state) in '
            'on-chip memory; in the split decode loop the GPUs run attention over the accumulated KV cache and exchange activations with '
            'the LPX per token.</p>'
            '<h4>Other figures: Rubin platform post</h4>'
            '<p><a href="https://developer.nvidia.com/blog/inside-the-nvidia-rubin-platform-six-new-chips-one-ai-supercomputer/">Inside the NVIDIA Rubin platform</a> '
            '(developer.nvidia.com):</p>'
            '<ul><li><b>Rubin GPU:</b> up to 288 GB HBM4 per GPU at up to 22 TB/s (Blackwell HBM3e: 8 TB/s). NVLink 6: 3.6 TB/s per GPU, '
            '28.8 TB/s per switch tray, 260 TB/s per NVL72 rack. NVLink-C2C to the CPU: 1.8 TB/s. PCIe Gen6: 256 GB/s.</li>'
            '<li><b>Vera CPU:</b> up to 1.5 TB LPDDR5X (SOCAMM) at up to 1.2 TB/s; 164 MB L3 (Grace: up to 480 GB at 512 GB/s). The post '
            'says LPDDR5X and HBM4 can be used as one coherent pool, which enables KV-cache offload.</li>'
            '<li><b>BlueField-4:</b> 800 Gb/s networking, 20M IOPS at 4K, 128 GB on-DPU memory at 250 GB/s. ConnectX-9: 1.6 Tb/s per GPU.</li>'
            '<li><b>Inference Context Memory Storage (ICMS):</b> a pod-level Ethernet-attached flash tier sized for petabytes, placed between '
            'the local tiers (HBM, DRAM, local SSD) and durable shared storage. The post claims up to 5&times; tokens/s versus traditional '
            'storage approaches; treat that as a vendor claim, not a workshop measurement.</li></ul>'
            '<h4>Units on the bars</h4>'
            '<p>Memory rows (SRAM, HBM4, LPDDR5X) show total memory bandwidth as quoted. Link rows show one direction, because a KV fetch '
            'streams one way: NVLink 6 3.6 TB/s bidirectional = 1.8 TB/s each way; NVLink-C2C 1.8 TB/s bidirectional = 0.9 TB/s each way; '
            'PCIe Gen6 x16 256 GB/s bidirectional = 128 GB/s each way; ConnectX-9 1.6 Tb/s per GPU = 200 GB/s; a BlueField-4 800 Gb/s '
            'port = 100 GB/s. Quoted as 256 GB/s against 800 Gb/s the gap looks 2.5&times;; per direction it is 128 against 100.</p>'
            '<h4>Not from the post</h4>'
            '<ul><li>Rubin GPU on-die SRAM (registers, L1/L2) figures are not in either post; the SRAM row is the LPX, a different chip.</li>'
            '<li>A single NVMe drive delivers tens of GB/s; the 256 GB/s figure is the PCIe Gen6 link, not a drive.</li>'
            '<li>The demo cluster is H100-class (80 GB HBM3 at about 3.35 TB/s per GPU): the same ladder with smaller numbers.</li></ul>'
            '<p class="dw-dim">Teaching point only: no tier is a free lunch. The scaling section introduces CPU offloading, KVCR peer reuse '
            'and ModelExpress peer weights as moves along this ladder.</p>'))


def s07_prefix_reuse():
    W = dict(code=420, resp=340, tool=190, inst=230)
    rows = row('Request 1', [seg('ctx', 'code + user task', W['code'])])
    rows += row('Request 2', [seg('ctx', 'code + user task', W['code']), seg('resp', 'assistant / tool-call response', W['resp']),
                              seg('tool', 'tool result', W['tool'])], s=1)
    x0 = 190 + 8
    brk = (f'<div class="brk" style="left:{x0}px;top:160px;width:{W["code"]}px" data-s="2"></div>'
           f'<div class="brk-lbl" style="left:{x0}px;top:198px;width:{W["code"]}px" data-s="2"><b>shared prefix</b>'
           'Already processed for request 1. The server can keep that working state and reuse it.</div>')
    x1 = x0 + W['code'] + 8
    w1 = W['resp'] + W['tool'] + 8
    brk += (f'<div class="brk c" style="left:{x1}px;top:160px;width:{w1}px" data-s="3"></div>'
            f'<div class="brk-lbl c" style="left:{x1}px;top:198px;width:{w1}px" data-s="3"><b>new context</b>'
            'Only this part needs prompt processing. Reuse shortens prefill; it does not speed up generating each new token.</div>')
    body = f'<div class="rows">{rows}</div>{brk}'
    body += ('<div class="banner" style="left:0;top:400px;width:1680px" data-s="3">'
             '<div><b>Cache locality determines prefill work.</b>'
             '<small>A matching cached prefix avoids recomputation. A worker without that prefix must repeat the prefill work.'
             '</small></div></div>')
    return slide(
        'Prefix reuse',
        kick('1.3', 'Prefix reuse'),
        'Prefix caching reduces repeated prefill',
        body, steps=3,
        notes=(
            '<p>Show successive requests with the repeated prefix highlighted and the newly appended content distinguished.</p>'
            '<p>The server can retain computation associated with a matching prefix and reuse it on subsequent requests, reducing '
            'repeated prompt-processing work. This does <b>not</b> inherently accelerate the generation of each new token.</p>'
            '<p><b>Emphasize the operational consequence:</b> inference servers retain valuable state, so the cost of a request depends '
            'on which server receives it and what that server already has cached. This motivates routing and cross-worker reuse later.</p>'
            '<p class="dw-dim">No separate live reuse experiment in this section.</p>'))


def s08_where_it_lands():
    body = MARKERS + overlay(
        arrow(420, 240, 758, 190, cls='g', s=1, head='fund-ah-g', mid=(600, 190)),
        arrow(420, 300, 758, 480, cls='dash', s=2, mid=(560, 300)),
    )
    body += node(0, 130, 420, 240,
                 '<h3><small>same session</small>Agent</h3>'
                 '<p>Sends <b>request 2</b>: the prefix from request 1 plus the new context.</p>')
    body += node(760, 60, 920, 260,
                 '<h3><small>holds the prefix from request 1</small>Server A · warm</h3>'
                 '<p>Reuses the cached working state and processes <b>only the new context</b> before generating.</p>'
                 '<div class="cost">prompt work<i style="width:150px"></i>new context only</div>', cls='g', s=1)
    body += node(760, 360, 920, 260,
                 '<h3><small>nothing cached for this session</small>Server B · cold</h3>'
                 '<p>No matching state. Recomputes the <b>entire context</b> before the first new token appears.</p>'
                 '<div class="cost">prompt work<i class="long" style="width:560px"></i>everything, again</div>', s=2)
    body += ('<div class="banner" style="left:0;top:440px;width:640px;height:190px" data-s="3">'
             '<div><b>Identical replicas stop being interchangeable</b> once they hold different cached state.'
             '<small>Which server a request lands on now changes its cost, its latency, and the capacity left for everyone else.</small></div></div>')
    return slide(
        'Where a request lands matters',
        kick('1.3', 'Prefix reuse'),
        'The cost of a request depends on where it lands',
        body, steps=3,
        notes=(
            '<p>Two servers running the same model. Server A served request 1 and still holds its working state; server B did not. '
            'The same request 2 costs very different amounts of prompt processing depending on which one receives it.</p>'
            '<p>This is the hook for the scaling section: cache-aware routing (send the request where the state is) and KVCR '
            '(move the state to where the compute is). Name them, do not explain them yet.</p>'))


def s09_caveats():
    cards = card('g', 'Derived',
                 '<p>Cached state is <b>computed from the context</b>. Lose it and the server can recompute it, at a cost in compute, '
                 'latency and capacity. The agent still sends the full context either way: its conversation history is not the '
                 'server&#8217;s cached computation.</p>', tag='recomputable, expensively', s=1)
    cards += card('c', 'Finite',
                  '<p>The GPU <b>cannot retain every prefix</b> it has ever processed. Cache competes with weights and workspace for the '
                  'same memory budget, and the active requests need room too.</p>', tag='one memory budget', s=2)
    cards += card('r', 'Evictable',
                  '<p>To make room, the engine may <b>evict reusable state</b>. The agent&#8217;s next request then needs recomputation. '
                  'Evicting a retained prefix is <b>not</b> the same as failing an active request.</p>', tag='eviction ≠ failure', s=3)
    return slide(
        'Derived, finite, evictable',
        kick('1.3', 'Prefix reuse'),
        'Cached state is derived, finite, and evictable',
        f'<div class="cards c3">{cards}</div>', steps=3,
        foot='Host memory as a second cache tier (<b>CPU offloading</b>) comes early in the scaling section, after concurrency and '
             'before ModelExpress.',
        notes=(
            '<p><b>Essential caveat:</b> cached state is derived from the context. In this simplified model it can be recomputed if lost, '
            'but doing so is expensive. The agent still sends the context needed for the request; its conversation history is distinct '
            'from the server&#8217;s cached computation. Cache loss therefore affects compute cost, latency and available capacity, even '
            'when the request can still be served.</p>'
            '<p><b>Capacity and eviction:</b> the GPU cannot retain every previously computed prefix indefinitely. An engine may evict '
            'reusable cached state to make room, so an agent&#8217;s next request can need recomputation. Keep eviction of retained prefixes '
            'distinct from failure of an active request.</p>'
            '<p class="dw-dim">Introduce CPU offloading early in scaling, after concurrency and before ModelExpress, not here.</p>'))


def s10_dgd():
    def ln(text, only=None):
        at = f' data-only="{only}"' if only else ''
        return f'<span class="ln"{at}>{text}</span>'
    code = (
        ln('<span class="k">apiVersion</span>: nvidia.com/v1beta1')
        + ln('<span class="k">kind</span>: <span class="v">DynamoGraphDeployment</span>', '3')
        + ln('<span class="k">metadata</span>: {<span class="k">name</span>: agent-baseline}')
        + ln('<span class="k">spec</span>:')
        + ln('  <span class="k">components</span>:')
        + ln('  - <span class="k">name</span>: Frontend', '1')
        + ln('    <span class="k">type</span>: <span class="v">frontend</span>       <span class="c"># HTTP in, tokens out · no GPU</span>', '1')
        + ln('  - <span class="k">name</span>: worker', '2')
        + ln('    <span class="k">type</span>: <span class="v">worker</span>', '2')
        + ln('    <span class="k">replicas</span>: <span class="p">1</span>', '2')
        + ln('    <span class="k">podTemplate</span>:', '2')
        + ln('      <span class="k">spec</span>:', '2')
        + ln('        <span class="k">containers</span>:', '2')
        + ln('        - <span class="k">name</span>: main', '2')
        + ln('          <span class="k">image</span>: nvcr.io/nvidia/ai-dynamo/vllm-runtime-nightly:20261103-e37f0b9-efa', '2')
        + ln('          <span class="k">command</span>: [python3, -m, <span class="v">dynamo.vllm</span>]', '2')
        + ln('          <span class="k">args</span>: [--model, nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4,', '2')
        + ln('                 --tensor-parallel-size, <span class="p">"2"</span>, --language-model-only]', '2')
        + ln('          <span class="k">resources</span>: {<span class="k">claims</span>: [{<span class="k">name</span>: gpu-main}]}   '
             '<span class="c"># or limits: {nvidia.com/gpu: 2}</span>', '2')
        + ln('        <span class="k">resourceClaims</span>:', '2')
        + ln('        - {<span class="k">name</span>: gpu-main, <span class="k">resourceClaimTemplateName</span>: demo-inference-gpus}', '2')
        + ln('<span class="c"># ResourceClaimTemplate demo-inference-gpus: exactly 2 devices of class gpu.nvidia.com</span>', '2')
    )
    left = f'<div class="code sm" style="position:absolute;left:0;top:0;width:1040px;height:640px">{code}</div>'
    right = ('<div style="position:absolute;left:1080px;top:0;width:600px;display:flex;flex-direction:column;gap:20px">'
             + card('g', 'Frontend · HTTP in, tokens out',
                    '<p>The OpenAI-compatible endpoint, running <b>without a GPU</b>. Separated from the engine on purpose; '
                    'the later experiments show why.</p>', s=1)
             + card('c', 'Worker · the engine on GPUs',
                    '<p>vLLM serving the model across two GPUs, claimed through <b>DRA</b>, in text-only mode for this workload. '
                    '<b>One replica</b> for now; scaling adds more.</p>', s=2)
             + card('a', 'One object for the operator',
                    '<p>The Dynamo operator <b>reconciles</b> this single resource into the Deployments, Pods and Services that '
                    'actually run.</p>', s=3)
             + '</div>')
    return slide(
        'The smallest useful DGD',
        kick('1.4', 'A Dynamo-managed deployment'),
        'The smallest useful DynamoGraphDeployment',
        left + right, steps=3,
        notes=(
            '<p>Show the smallest useful DGD for the service and explain:</p>'
            '<ul><li>The HTTP frontend is separated from the inference engine running on GPUs.</li>'
            '<li>The reasons for that separation become clearer in the later experiments.</li>'
            '<li>The Dynamo operator reconciles the DGD into Kubernetes resources.</li></ul>'
            '<p>Start the deployment while explaining the manifest (see the demo slide). The demo profile uses eager execution and '
            'omits performance tuning options.</p>'
            '<p>The GPUs come from a DRA ResourceClaim, as on our cluster; on a device-plugin cluster <code>limits: {nvidia.com/gpu: 2}</code> '
            'takes its place. <code>--language-model-only</code> is the text-only mode chosen for the coding-agent workload.</p>'
            '<p class="dw-dim">The image is the public nightly the take-home uses. The live demo runs a pinned 1.6.0 development build of the '
            'same runtime.</p>'))


def s11_operator():
    body = MARKERS + overlay(
        arrow(190, 192, 190, 258),
        arrow(380, 325, 518, 125, s=1, mid=(450, 125)),
        arrow(380, 325, 518, 375, s=2, mid=(450, 375)),
    )
    body += node(0, 40, 380, 150, '<span class="chip">kind: DynamoGraphDeployment</span><h3>agent-baseline</h3>')
    body += node(0, 260, 380, 130, '<h3><small>watches &amp; reconciles</small>Dynamo operator</h3>')
    body += node(520, 40, 500, 170,
                 '<h3><small>frontend</small>Deployment → Pod</h3>'
                 '<p>No GPU. Plus a <b>Service</b>: <code>agent-baseline-frontend:8000</code></p>', cls='g', s=1)
    body += node(520, 290, 500, 170,
                 '<h3><small>worker</small>Deployment → Pod</h3>'
                 '<p>Requests <b>2 GPUs</b>. Runs the vLLM engine with the model weights and the KV cache pool.</p>', cls='c', s=2)
    listing = (
        '<span class="c">$ kubectl -n workshop get pods,svc</span>\n'
        'NAME                                   READY  STATUS\n'
        '<span class="v">pod/agent-baseline-frontend-7c9d-x2kq</span>  1/1    Running\n'
        '<span class="v">pod/agent-baseline-worker-5f4b-m7tz</span>    1/1    Running\n'
        '\n'
        'NAME                              TYPE       PORT(S)\n'
        '<span class="v">service/agent-baseline-frontend</span>   ClusterIP  8000/TCP\n'
        '\n'
        '<span class="c">$ kubectl wait --for=condition=Ready dgd/agent-baseline</span>\n'
        '<span class="c">$ kubectl port-forward \\</span>\n'
        '<span class="c">    svc/agent-baseline-frontend 8000:8000</span>')
    body += f'<div class="code sm" style="position:absolute;left:1040px;top:40px;width:640px;height:420px" data-s="3">{listing}</div>'
    body += ('<div class="banner" style="left:0;top:500px;width:1680px" data-s="3">'
             '<div><b>Show the resources that actually appear</b>, not just the manifest.'
             '<small>Frontend and worker Pods, the frontend Service, and the DGD status going Ready. Names and namespace are illustrative; '
             'read them off the live cluster.</small></div></div>')
    return slide(
        'What the operator creates',
        kick('1.4', 'A Dynamo-managed deployment'),
        'One object in, the real resources out',
        body, steps=3,
        notes=(
            '<p>The Dynamo operator reconciles the DGD into Kubernetes resources. Show the resources that actually appear, including '
            'the frontend and worker Pods.</p>'
            '<p>The service is reached like any OpenAI-compatible server: port-forward (or expose) the frontend Service and call '
            '<code>/v1/models</code> and <code>/v1/chat/completions</code>.</p>'
            '<p class="dw-dim">The listing is a mock-up. Confirm resource names against the pinned operator before showing it as a '
            'static fallback.</p>'))


def s12_startup():
    total, w_load, w_init = 493, 267, 144
    other = total - w_load - w_init
    px = 1680 / total
    tl = ('<div class="tl" data-s="1">'
          f'<div class="ph o" style="width:{other * px:.0f}px"><h4>Everything else</h4><small class="only" data-only="2 3">{other} s</small></div>'
          f'<div class="ph w" style="width:{w_load * px:.0f}px"><h4>Model weight loading</h4><small class="only" data-only="2 3">{w_load} s · about 54%</small></div>'
          f'<div class="ph i" style="width:{w_init * px:.0f}px"><h4>Engine initialization</h4><small class="only" data-only="2 3">{w_init} s</small></div>'
          '</div>')
    tick = f'<div class="tick" style="left:1676px" data-s="2"><span>Ready · {total} s · 8 min 13 s</span></div>'
    caps = ('<div class="tlcap" data-s="1">'
            f'<div style="width:{other * px:.0f}px"><p><strong>Before and after</strong>Scheduling, image pull, process start, and the readiness tail.</p></div>'
            f'<div style="width:{w_load * px:.0f}px"><p><strong>Weights into GPU memory</strong>Reading the checkpoint from storage. The largest single phase. '
            'Its length depends on the storage path, which is the ModelExpress story in scaling.</p></div>'
            f'<div style="width:{w_init * px:.0f}px"><p><strong>The engine state from 1.2</strong>Compilation, warm-up, graph capture, KV-cache allocation. '
            'Comes back in recovery.</p></div></div>')
    chips = ('<div class="chips" data-s="3">'
             '<div><span class="lab">measured</span><span><b>Super VL · TP2 · 2 × H100 · native loading from shared storage (EFS) · compiled benchmark profile.</b> '
             'One fixed-order trial with five-second Ready polling: a labeled example, not a distribution, and not a cold-download or '
             'local-NVMe comparison.</span></div></div>')
    return slide(
        'Startup timeline',
        kick('1.4', 'A Dynamo-managed deployment'),
        'Ready takes minutes, and weights are only part of it',
        tl + tick + caps + chips, steps=3,
        notes=(
            '<p>Show the startup timeline, distinguishing model weight loading from engine initialization and the full time until the '
            'worker can serve a request. Include scheduling and image availability where they materially contribute.</p>'
            '<p>Numbers: the matched text-only Super VL TP2 H100 measurement with native EFS loading took about 493 s to observed Ready, '
            'including 267 s of model loading and 144 s of engine initialization (about 54% of startup is weight loading). The compiled '
            'benchmark profile is separate from the eager presenter demo; the eager intro retake took about 461 s to Ready.</p>'
            '<p class="dw-dim">The timing dependency is still open: start the deployment while explaining the manifest, and retain this '
            'measured timeline if live initialization exceeds its slot. Long preparation must not consume the rest of the introduction.</p>'))


def s13_demo():
    steps = [
        ('1', 'Effective DGD', 'The manifest as applied, with the pinned image and model.', 'kubectl get dgd agent-baseline -o yaml'),
        ('2', 'Deploy, then keep talking', 'Pod scheduling and model startup run continuously inside this step.', 'kubectl apply -f agent-baseline.yaml'),
        ('3', 'Operator-created resources', 'Deployments, Pods and the frontend Service appear.', 'kubectl get pods,svc'),
        ('4', 'Readiness and timing', 'Ready condition plus an immediate summary of where the time went.', 'kubectl wait --for=condition=Ready dgd/…'),
        ('5', 'Model discovery', 'The frontend lists the model the worker registered.', 'GET /v1/models'),
        ('6', 'One inference request', 'A streaming coding request through the frontend.', 'POST /v1/chat/completions'),
    ]
    cards = ''.join(
        f'<div class="card"><span class="num">{n}</span><div><h3>{h}</h3><p>{p}</p><span class="chip">{esc(c)}</span></div></div>'
        for n, h, p, c in steps)
    return slide(
        'Demo: deploy a single replica',
        kick('1.4', 'Demo'),
        'Demo: deploy a single replica',
        f'<div class="demo">{cards}</div>',
        sub='Keypress-controlled terminal demo. Resource/timing and worker-log panes alongside; the service stays up for 1.5.',
        foot='Eager execution, no performance tuning. If initialization runs past its slot, switch to the recorded run and the '
             'measured timeline rather than waiting.',
        notes=(
            '<p>Presenter implementation: the single-replica terminal demo (demos/01-single-replica). Keypress-controlled steps show '
            'the effective DGD, deployment, operator-created resources, readiness and its immediate timing summary, then HTTP model '
            'discovery and an inference request. Pod/model startup runs continuously within one step. Tmux adds resource/timing and '
            'worker-log panes; a labeled offline rehearsal supports presentation iteration.</p>'
            '<p>The service is retained for 1.5. The introductory demo uses eager execution and omits performance tuning options; the '
            'compiled startup benchmarks have their own separately qualified profile.</p>'))


def s14_metrics():
    # request timeline strip
    toks = ''.join(f'<circle class="tok" cx="{x}" cy="70" r="9"/>' for x in range(640, 1500, 86))
    strip = (
        '<svg class="strip" viewBox="0 0 1680 200" aria-hidden="true">'
        '<line class="ax" x1="30" y1="70" x2="1650" y2="70"/>'
        '<circle class="req" cx="40" cy="70" r="11"/><text x="30" y="36">request sent</text>'
        '<circle class="ft" cx="560" cy="70" r="11"/><text x="560" y="36" text-anchor="middle">first token</text>'
        f'{toks}<circle class="ft" cx="1560" cy="70" r="11"/><text x="1560" y="36" text-anchor="middle">last token</text>'
        '<g data-s="1"><path class="br g" d="M46 96 v14 h508 v-14"/><text class="m" x="300" y="132" text-anchor="middle">time to first token</text></g>'
        '<g data-s="2"><path class="br c" d="M646 96 v14 h74 v-14"/><text class="m" x="683" y="132" text-anchor="middle">inter-token latency</text></g>'
        '<g data-s="3"><path class="br d" d="M46 152 v14 h1508 v-14"/><text class="m d" x="800" y="190" text-anchor="middle">end-to-end request latency = request sent → last token</text></g>'
        '</svg>')
    rows = [
        ('Time to first token', 'TTFT', 'How long before the answer <b>starts arriving</b>?'),
        ('Generation speed', 'inter-token latency · tokens/s per user', 'How quickly does the answer arrive <b>once generation starts</b>?'),
        ('End-to-end request latency', 'request sent → last token', 'How long does the <b>whole inference request</b> take?'),
        ('Throughput', 'output tokens/s · requests/s', 'How much work does the service complete <b>under this load</b>?'),
        ('Errors and unsuccessful requests', 'error rate · incomplete responses', 'Which requests <b>fail to complete</b> successfully?'),
    ]
    table = ''.join(f'<div class="r" data-s="{i + 1}"><div class="n">{n}<small>{m}</small></div><div class="q">{q}</div></div>'
                    for i, (n, m, q) in enumerate(rows))
    return slide(
        'Five measurements',
        kick('1.5', 'Baseline and metrics with AIPerf'),
        'Five measurements, in the agent&#8217;s terms',
        strip + f'<div class="mt">{table}</div>', steps=5,
        notes=(
            '<p>Explain the important measurements in terms of the agent&#8217;s experience. Define the metrics here; choose the concrete '
            'SLO targets and percentiles during workload preparation. Use the same evaluation criteria throughout the later sections.</p>'
            '<table><tr><th>Measurement</th><th>Audience interpretation</th></tr>'
            '<tr><td>Time to first token</td><td>How long before the answer starts arriving?</td></tr>'
            '<tr><td>Generation speed / inter-token latency</td><td>How quickly does the answer arrive once generation starts?</td></tr>'
            '<tr><td>End-to-end request latency</td><td>How long does the whole inference request take?</td></tr>'
            '<tr><td>Throughput</td><td>How much work does the service complete under this load?</td></tr>'
            '<tr><td>Errors / unsuccessful requests</td><td>Which requests fail to complete successfully?</td></tr></table>'
            '<p class="dw-dim">Later: tokens/s per GPU describes efficiency, tokens/s per user describes interactivity; never derive '
            'per-user speed by dividing aggregate throughput by the number of agent sessions.</p>'))


def s14b_pareto():
    # SemiAnalysis InferenceX, GLM-5.2/5.3 744B agentic workload, Vera Rubin NVL72 FP4 with Dynamo + TensorRT-LLM, KV offload on.
    # Points read from the published chart (official preview, Nov 6 2026): P90 interactivity (tok/s per user), M tok/s per all-in MW.
    P = [(203, 45.3), (238, 41.6), (253, 34.3), (418, 8.3), (610, 4.2), (800, 2.3), (1052, 0.5)]
    X0, XS, Y0, YS = 110, 1540 / 1100, 330, 300 / 50
    px = lambda u, t: (X0 + u * XS, Y0 - t * YS)
    pts = [px(u, t) for u, t in P]

    def spline(ps):  # Catmull-Rom through the measured points
        d = f'M{ps[0][0]:.1f} {ps[0][1]:.1f}'
        for i in range(len(ps) - 1):
            p0 = ps[i - 1] if i > 0 else ps[i]
            p1, p2 = ps[i], ps[i + 1]
            p3 = ps[i + 2] if i + 2 < len(ps) else ps[i + 1]
            c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
            c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
            d += f' C{c1[0]:.1f} {c1[1]:.1f}, {c2[0]:.1f} {c2[1]:.1f}, {p2[0]:.1f} {p2[1]:.1f}'
        return d
    xt = ''.join(f'<line class="tk" x1="{X0 + v * XS:.0f}" y1="{Y0}" x2="{X0 + v * XS:.0f}" y2="{Y0 + 12}"/>'
                 f'<text x="{X0 + v * XS:.0f}" y="{Y0 + 38}" text-anchor="middle">{v:,}</text>' for v in range(0, 1001, 200))
    yt = ''.join(f'<line class="tk" x1="98" y1="{Y0 - v * YS:.0f}" x2="110" y2="{Y0 - v * YS:.0f}"/>'
                 f'<text x="86" y="{Y0 - v * YS + 6:.0f}" text-anchor="end">{v}M</text>' for v in range(10, 51, 10))
    marks = ''.join(f'<circle class="ring" cx="{x:.1f}" cy="{y:.1f}" r="16"/><circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="9"/>' for x, y in pts)
    chart = (
        '<svg class="pfc" viewBox="0 0 1680 410" aria-hidden="true">'
        f'<path class="ax" d="M110 20 L110 {Y0} L1650 {Y0}"/>' + xt + yt +
        f'<text class="t" x="880" y="{Y0 + 70}" text-anchor="middle">P90 interactivity: tokens per second, per user</text>'
        f'<text class="t" x="40" y="{Y0 // 2 + 10}" text-anchor="middle" transform="rotate(-90 40 {Y0 // 2 + 10})">tokens per second, per all-in megawatt</text>'
        f'<g data-s="1"><path class="cv" d="{spline(pts)}"/>{marks}'
        f'<text class="lab" x="{pts[0][0] + 32:.0f}" y="{pts[0][1] + 7:.0f}">most tokens per megawatt</text>'
        f'<text class="lab" x="{pts[-1][0] - 28:.0f}" y="{pts[-1][1] - 26:.0f}" text-anchor="end">fastest for each agent</text>'
        '<text class="tl" x="1000" y="178" text-anchor="middle">Vera Rubin NVL72 FP4 · Dynamo + TensorRT-LLM</text>'
        '<text class="tl" x="1000" y="204" text-anchor="middle">GLM-5.3 744B agentic workload · KV offload on · measured points</text></g>'
        '</svg>')
    cards = ('<div class="pf-cards">'
             + card('g', 'Run at the left end: the most tokens per megawatt',
                    '<p><b class="k">you gain</b> The lowest cost per token and the most sessions per rack. The batch is always full, so the hardware earns its keep.</p>'
                    '<p><b class="k">you give up</b> Speed for each agent. Every token takes longer, so a forty-turn task stretches and tool loops close slowly.</p>'
                    '<p><b class="k">pick it for</b> Work nobody is watching: RL rollouts, evaluations, overnight batch pipelines.</p>', s=2)
             + card('c', 'Run at the right end: the fastest stream for each agent',
                    '<p><b class="k">you gain</b> Turns come back fast. An interactive coding session feels live and its tool loops close quickly.</p>'
                    '<p><b class="k">you give up</b> Ten to a hundred times fewer tokens per megawatt, so cost per token climbs and fewer sessions fit per rack.</p>'
                    '<p><b class="k">pick it for</b> Humans in the loop and latency promises: interactive assistants, customer-facing chat.</p>', s=2)
             + '</div>')
    return slide(
        'Interactivity versus throughput',
        kick('1.5', 'Baseline and metrics with AIPerf'),
        'Faster for each agent, or more tokens per megawatt',
        chart + cards, steps=2,
        foot='The rule: pick the slowest per-user speed your workload tolerates, then run at the highest throughput that still meets it. '
             'For most services that lands near the knee. Source: SemiAnalysis InferenceX preview, read from the chart on Nov 6, 2026.',
        notes=(
            '<p>The real Pareto frontier for one model and one system: GLM-5.2/5.3 744B on the agentic workload, Vera Rubin NVL72 FP4 with '
            'Dynamo and TensorRT-LLM, KV offload on, all-in power 3.3 kW per VR200. Each point is a measured configuration.</p>'
            '<ul><li>x axis: P90 interactivity, output tokens per second seen by one user. This is the number an agent feels.</li>'
            '<li>y axis: token throughput per all-in utility megawatt, the datacenter version of tokens per second per GPU. At 3.3 kW per '
            'chip a megawatt is roughly 300 chips.</li>'
            '<li>Left end: about 200 tokens per second per user at 45 million per megawatt. Right end: about 1,050 per user at half a million '
            'per megawatt, roughly one percent of the throughput. The knee is between 250 and 420 per user: a 70 percent gain in speed '
            'costs three quarters of the throughput.</li></ul>'
            '<p><b>Why choose one end.</b> Throughput per megawatt is cost: every point left is cheaper per token and holds more sessions per '
            'rack, paid for in per-agent speed, which for a coding agent means slower tool loops and longer tasks. Interactivity is '
            'experience: every point right makes the session feel live, paid for in cost per token and in how many sessions one rack can '
            'carry. Batch work (RL rollouts, evaluations, overnight pipelines) belongs on the left; anything with a human waiting or a '
            'latency SLO belongs toward the right. The rule of thumb: decide the slowest per-user speed the workload tolerates, then run at '
            'the highest throughput that still meets it. The rest of the workshop is about moving the whole frontier up and to the right.</p>'
            '<p class="dw-dim">Values were read off the InferenceX chart (inferencex.semianalysis.com/infx/inference/glm-5-3), labelled an '
            'official preview.</p>'))


def s15_baseline():
    top = ('<div class="cards c2" style="margin-bottom:24px">'
           + card('g', 'Per-request measurements',
                  '<p>TTFT, generation speed, latency and errors describe <b>one inference call</b>. That is what AIPerf reports and what '
                  'the serving system controls.</p>', tag='what we measure', s=1)
           + card('c', 'The whole agent session',
                  '<p>A session is <b>many requests</b> with tool time in between. What the developer feels is the sum; the per-request '
                  'numbers explain why it changed.</p>', tag='what the user feels', s=2)
           + '</div>')
    bottom = ('<div class="cards c2">'
              + card('', 'What the baseline replays',
                     '<ul><li>A <b>prebuilt agentic trace</b> (the pinned AgentX corpus) sent at the frontend by AIPerf.</li>'
                     '<li>Controlled and repeatable: the <b>same workload all day</b>. Only offered load, serving configuration and '
                     'injected failures change.</li></ul>')
              + card('', 'What stays open until workload preparation',
                     '<ul><li>Exact agent, task and trace for the explanatory visual.</li>'
                     '<li>SLO thresholds, reporting percentiles and metric windows.</li>'
                     '<li>The increasing-demand experiment waits for the <b>scaling</b> section.</li></ul>')
              + '</div>')
    return slide(
        'Baseline: a prebuilt agent trace',
        kick('1.5', 'Baseline and metrics with AIPerf'),
        'Baseline: a prebuilt agent trace, controlled and repeatable',
        top + bottom, steps=2,
        foot='<b>Next: AIPerf.</b> How the load is generated, what the reports contain, and how to read them for the rest of the day.',
        notes=(
            '<p>Use a prebuilt agentic trace to establish a baseline against the single-replica service from 1.4. Choosing the exact '
            'agent, task and trace is deferred; the controlled benchmark workload is the pinned AIPerf AgentX scenario.</p>'
            '<p>Distinguish individual-request measurements from an entire agent session. Save the increasing-demand experiment for '
            'section 2.</p>'
            '<p>Transition: the AIPerf section that follows explains the tool itself.</p>'))


# Trimmed on 2026-11-05: s02_growing_context, s04_state, s09_caveats, s11_operator and s15_baseline are kept as
# functions but no longer shown (s00_plan, the timing table, was dropped on 2026-11-05 too); the demo slide now comes before the DGD manifest.
SLIDES = [s01_agent_loop, s03_zoom, s05_prefill_decode, s06_memory, s06b_tiers, s07_prefix_reuse,
          s08_where_it_lands, s13_demo, s10_dgd, s12_startup, s14_metrics, s14b_pareto]


def render_slides():
    return [f() for f in SLIDES]


if __name__ == '__main__':
    for i, s in enumerate(render_slides()):
        import re
        print(i, re.search(r'data-title="([^"]*)"', s).group(1), len(s))
