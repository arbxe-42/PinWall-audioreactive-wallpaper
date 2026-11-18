"""Score stem-label settings against ALL human truth at once (no stem-derived truth here):
  ADR: Adrenaline kick lane 63-127 s (moments.json), F at best shift (+-50 ms)
  01 / 02 / 04: the user's kick taps in Kick Check (bench/annotations), P/R inside the tapped span at the best
                shift (01 was tapped on the K3s, the rest not; the shift absorbs it). 02/04 were only partly tapped
                ("my markings repeat", "only marked part"), so their precision is a lower bound.
  quiet: kicks labelled where the user said there are none (01 <53 s and >296 s; 02 131-177 s)
  listener/.venv/Scripts/python.exe bench/label_human.py [gate_db=..,..] [rise_db=..] [kick_win=..]
"""
import itertools, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bench as B, stem_labels as SL
from label_eval import best_shift
FULL = os.path.join(B.MUSIC, "analysis", "full")
grid = {kv.split("=")[0]: [float(v) for v in kv.split("=")[1].split(",")] for kv in sys.argv[1:] if "=" in kv}
X = {n: B.read_mono(os.path.join(FULL, n, "drums.flac")) for n in ("14", "01", "02", "04")}
hk, hs = B.adrenaline_hand_lanes(); hk = np.array([t for t in hk if 63 <= t <= 127]); hs = np.array([t for t in hs if 63 <= t <= 127])
hks = np.sort(np.concatenate([hk, hs]))
T = {}
for n in ("01", "02", "04"):
    f = "01_taps_backup_late.json" if n == "01" else f"{n}.json"
    t = np.array(sorted(json.load(open(os.path.join(HERE, "annotations", f), encoding="utf-8"))["kick_add"]))
    T[n] = t[t >= 54] if n == "01" else t
W08 = np.array(json.load(open(os.path.join(HERE, "annotations", "08.json"), encoding="utf-8"))["wrong"])
X["08"] = B.read_mono(os.path.join(FULL, "08", "drums.flac"))
W14 = np.array(json.load(open(os.path.join(HERE, "annotations", "14.json"), encoding="utf-8"))["wrong"])   # labels the user marked wrong
keys = list(grid) or ["gate_db"]
vals = [grid[k] for k in keys] if grid else [[20.0]]
for combo in itertools.product(*vals):
    P = dict(zip(keys, combo))
    LL = {n: SL.label(x, sr, **P) for n, (x, sr) in X.items()}
    L = {n: v["kicks"] for n, v in LL.items()}
    hits14 = np.sort(np.concatenate([LL["14"]["kicks"], LL["14"]["snares"]]))
    hits14 = hits14[(hits14 >= 62.5) & (hits14 <= 127.6)]
    fb = max((best_shift(hits14, 63 + (hks - 63) * sc) for sc in np.arange(0.994, 1.0061, 0.001)), key=lambda z: z[0])
    k = L["14"][(L["14"] >= 62.5) & (L["14"] <= 127.6)]
    f, sh, p, r = max((best_shift(k, 63 + (hk - 63) * sc) for sc in np.arange(0.994, 1.0061, 0.001)), key=lambda z: z[0])
    row = [f"ADR kicks F {f:.2f} (P {p:.2f} R {r:.2f}) kick+snare F {fb[0]:.2f} (P {fb[2]:.2f} R {fb[3]:.2f})"]
    fs = [f]
    for n in ("01", "02", "04"):
        t = T[n]
        # only the stretches the user actually tapped (gaps over 3 s split them)
        cuts = np.where(np.diff(t) > 3.0)[0]
        segs = np.split(t, cuts + 1)
        inside = np.zeros(len(L[n]), bool)
        for sg in segs:
            inside |= (L[n] >= sg.min() - 0.3) & (L[n] <= sg.max() + 0.3)
        kk = L[n][inside]
        f2, sh2, p2, r2 = best_shift(kk, t, -0.1, 0.45, 0.06)
        row.append(f"{n} P {p2:.2f} R {r2:.2f}"); fs.append(f2)
    wr = int(sum(1 for t in W14 if np.min(np.abs(L["14"] - t)) <= 0.02))
    row.append(f"ADR wrong-marked still kicks {wr}/{len(W14)}")
    row.append(f"825hp wrong-marked still kicks {int(sum(1 for t in W08 if np.min(np.abs(L['08'] - t)) <= 0.02))}/{len(W08)}")
    quiet = int(((L["01"] < 53) | (L["01"] > 296)).sum() + ((L["02"] > 131) & (L["02"] < 177)).sum())
    print(P, " | ".join(row), f"| quiet-part kicks {quiet} | mean F {np.mean(fs):.2f}", flush=True)
