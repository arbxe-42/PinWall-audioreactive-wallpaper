"""Builds bench/report.html from bench/results.json (run bench.py first)."""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
S, R = D["summary"], D["results"]


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def lane(y, times, w0, w1, W, color, h=14, width=1.5, dash=None):
    out = []
    for t in times:
        if w0 <= t <= w1:
            x = (t - w0) / (w1 - w0) * W
            d = f' stroke-dasharray="{dash}"' if dash else ""
            out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y}" y2="{y + h}" stroke="{color}" stroke-width="{width}"{d}/>')
    return "".join(out)


def timeline(r, a=None, b=None):
    w0, w1 = r["window"]
    if a is not None:
        w0, w1 = a, b
    W = 1100
    rows = [
        ("drum hits (truth)", r.get("drum_hits", []), "#8a8a8a"),
        ("kick truth", r["truth_kick"], "#ff4d6d"),
        ("beats: locked", [t for t, l, *_ in r["beats"] if l], "#b6ff2e"),
        ("beats: loose", [t for t, l, *_ in r["beats"] if not l], "#555"),
        ("fired kick", r.get("fired_kick", []), "#ff2bd6"),
        ("drop: truth / detected", [r["drop_true"]], "#ffe14a"),
    ]
    svg = [f'<svg viewBox="0 0 {W + 150} {len(rows) * 22 + 26}" class="tl">']
    for i, (name, ts, col) in enumerate(rows):
        y = 6 + i * 22
        svg.append(f'<text x="{W + 8}" y="{y + 12}" class="lab">{name}</text>')
        svg.append(f'<line x1="0" x2="{W}" y1="{y + 7}" y2="{y + 7}" stroke="#222"/>')
        svg.append(lane(y, ts, w0, w1, W, col))
        if name.startswith("drop"):
            svg.append(lane(y, r["drops"], w0, w1, W, "#22e6ff", width=3))
    for s in range(int(w0) + 1, int(w1) + 1):
        if s % 5 == 0:
            x = (s - w0) / (w1 - w0) * W
            svg.append(f'<text x="{x:.0f}" y="{len(rows) * 22 + 20}" class="tick">{s}s</text>')
    svg.append("</svg>")
    return "".join(svg)


rows = []
for r in R:
    k = r["kick"]
    rows.append(f"""<tr><td>{r['num']}</td><td>{html.escape(r['title'][:42])}</td>
<td>{r['bpm_est']:.1f} / {r['bpm_true']}</td><td>{'yes' if r['tempo_exact'] else ('x2' if r['tempo_octave'] else 'no')}</td>
<td>{pct(r['locked_frac'])}</td><td>{pct(r['beat_on_drum'])}</td><td>{r['beat_err_ms']}</td>
<td>{pct(k['precision'])}</td><td>{k['phantom_per_min']}</td>
<td>{'yes' if r['drop_hit'] else 'no'}</td><td>{r['false_drops']}</td></tr>""")

zooms = []
for r in R:
    w0 = r["drop_true"] - 3
    zooms.append(f"<h3>{r['num']} · {html.escape(r['title'])} <span>zoom: 3 s before the drop to 9 s after</span></h3>"
                 + timeline(r, w0, w0 + 12))

hand = next((r.get("hand") for r in R if r.get("hand")), None)
k, sn = S["kick"], S["snare"]
page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Pin Wall detection bench</title>
<style>
body{{background:#07040b;color:#ddd;font:15px/1.5 system-ui,sans-serif;margin:32px;max-width:1300px}}
h1{{color:#b6ff2e;font-weight:600}} h2{{color:#ff2bd6;margin-top:40px}} h3{{font-size:14px;margin:22px 0 4px;color:#eee}} h3 span{{color:#777;font-weight:400}}
table{{border-collapse:collapse;font-size:13px}} td,th{{padding:4px 10px;border-bottom:1px solid #222;text-align:left}} th{{color:#999;font-weight:500}}
.big{{display:flex;gap:14px;flex-wrap:wrap}} .card{{background:#120c1a;border:1px solid #2a2033;border-radius:10px;padding:14px 18px;min-width:180px}}
.card b{{display:block;font-size:30px;color:#22e6ff}} .card i{{font-style:normal;color:#999;font-size:13px}}
.tl{{width:100%;background:#0d0912;border-radius:6px}} .lab{{fill:#999;font-size:11px}} .tick{{fill:#666;font-size:10px}}
p.note{{color:#aaa;max-width:900px}}
</style></head><body>
<h1>Pin Wall · detection bench</h1>
<p class="note">The streaming detector (<code>listener/detect.py</code>) ran on the full mix of {S['clips']} of your tracks, each
from 30 s before a 48 s window around its drop, exactly as it would hear them live. Truth comes from each track's
isolated drum stem (every drum attack, plus kicks where the low end jumps). Nothing was played out loud.</p>
<div class="big">
<div class="card"><b>{pct(S['beat_on_drum'])}</b><i>locked beats that land on a real drum hit (±50 ms)</i></div>
<div class="card"><b>{S['beat_err_ms_median']:+.0f} ms</b><i>median beat timing vs the drum attack</i></div>
<div class="card"><b>{pct(S['tempo_exact'])}</b><i>tempo exact ({pct(S['tempo_octave'])} counting double/half time)</i></div>
<div class="card"><b>{pct(S['locked_frac'])}</b><i>of the time the clock is locked (the rest is loose mode: no hard hits)</i></div>
<div class="card"><b>{S['drop_hit']}/{S['clips']}</b><i>labelled drops caught (±1 s); {S['false_drops']} other big jumps also trigger</i></div>
<div class="card"><b>{S['cpu_x_realtime'] * 100:.1f}%</b><i>of one CPU core, live</i></div>
</div>

<h2>What the wallpaper uses, and what it ignores</h2>
<p class="note"><b>Uses the beat clock.</b> Every hard hit lands on a predicted beat, so a hit can never land off the beat, and
when the clock isn't sure (breaks, ambient, talk) it goes loose and hard hits stop. Each beat carries an accent (how hard that
beat position has been hitting over the last bars) so the visuals punch harder on the beats that really slam.<br>
<b>Ignores kick and snare labels for hard hits.</b> Telling a kick from a bass note or a snare from a clap in a full mix is
the weak part: fired kicks are right {pct(k['precision'])} of the time ({k['phantom_per_min']}/min wrong), snares only
{pct(sn['precision'])}. That is exactly the phantom-hit problem you were worried about, so they only shade the colour of an
effect, never trigger one.<br>
<b>Drops</b> fire the big shatter only on a jump of at least 8 dB in loudness and bass after a quieter stretch, then wait
30 s. It misses some drops rather than shattering on a fake one.</p>

<h2>Your K3 speakers</h2>
<p class="note">Your hand-fixed Adrenaline kicks sit <b>+242 ms</b> after the drum stem's kicks (48 of your 56 kicks
line up within 25 ms at that offset, measured against the low end's onset, which itself trails the click by ~25 ms), so about
250 to 265 ms after the attack. That is the Bluetooth delay you heard them through. The listener waits that long before sending hits
whenever the K3 speakers are the output, and sends them immediately on the laptop speakers or wired output.</p>

<h2>Per track</h2>
<table><tr><th>#</th><th>track</th><th>bpm found / analysed</th><th>tempo</th><th>locked</th><th>beats on drums</th>
<th>beat ms</th><th>kick label right</th><th>kick wrong/min</th><th>drop</th><th>other jumps</th></tr>
{''.join(rows)}</table>

<h2>Timelines around each drop</h2>
<p class="note">grey = every drum hit · red = kicks · green = locked beats · dark = loose beats · magenta = fired kick labels ·
yellow = labelled drop · cyan = detected drop</p>
{''.join(zooms)}
</body></html>"""
open(os.path.join(HERE, "report.html"), "w", encoding="utf-8").write(page)
print("wrote bench/report.html")
