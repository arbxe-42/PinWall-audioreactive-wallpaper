"""Score hit lists the same way for every trigger (KickNet activations or the live kick_fast).

Machine truth (stem-derived, NOT human): demucs drum stem onsets per track (bench.drum_hits)
  kick  P/R/F: hits vs stem kicks, one-to-one, +-50 ms
  both  P/R/F: hits vs stem kicks + snares
  phantom/min: hits with no drum onset of any kind within 50 ms on the stem (vocal, bass, pad hits)
  sent: median ms from the stem kick to the moment the hit is sent (detection latency)
Human truth: Adrenaline 63-127 s vs the user's kick + snare lanes (bench/hand_fast.py rules).

  python bench/kn_score.py bench/kn_acts_full_lag3.npz --src full [--lag 3]
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kn_train as K  # noqa: E402

FPS = 100.0


def pick2(A, tk, ts, gap=9):
    """Fire on frame n when the kick activation >= tk or the snare activation >= ts, while rising."""
    out, last = [], -10 ** 9
    k, s = A[:, 0], A[:, 1]
    for n in range(1, len(A)):
        if n - last < gap:
            continue
        if (k[n] >= tk and k[n] >= k[n - 1]) or (s[n] >= ts and s[n] >= s[n - 1]):
            out.append(n); last = n
    return np.array(out, int)


def kn_hits(A, t0, lag, tk, ts, gap=9):
    fr = pick2(A, tk, ts, gap)
    return t0 + (fr - lag + 1) / FPS, t0 + (fr + 1) / FPS


def machine(hits, nums, src):
    """hits: num -> (times, emit times). Returns dict of machine-truth scores."""
    agg = {"kick": [0, 0, 0], "both": [0, 0, 0]}; lat = []; ph = 0; dur = 0.0; per = {}
    for n in nums:
        F, k, s, t0, a, b = K.load(n, src)
        allh = np.sort(K.ALLH[(n, src)])
        tt, em = hits[n]
        m = (tt >= a) & (tt <= b); tt, em = tt[m], em[m]
        dur += (b - a) / 60
        for head, truth in (("kick", k), ("both", np.concatenate([k, s]))):
            truth = np.sort(truth[(truth >= a) & (truth <= b)])
            tp, _ = K.match(tt, truth)
            agg[head][0] += tp; agg[head][1] += len(tt); agg[head][2] += len(truth)
        ks = np.sort(k)
        for x_, e_ in zip(tt, em):
            if len(ks):
                j = np.argmin(np.abs(ks - x_))
                if abs(ks[j] - x_) <= 0.05:
                    lat.append(e_ - ks[j])
        nph = sum(1 for x_ in tt if not len(allh) or np.min(np.abs(allh - x_)) > 0.05)
        ph += nph
        per[n] = (len(tt), nph)
    out = {}
    for head, (tp, nd, nt) in agg.items():
        p, r = tp / max(1, nd), tp / max(1, nt)
        out[head] = (round(p, 3), round(r, 3), round(2 * p * r / (p + r + 1e-9), 3))
    out["phantom_per_min"] = round(ph / max(1e-9, dur), 1)
    out["hits_per_min"] = round(sum(v[0] for v in per.values()) / max(1e-9, dur), 1)
    out["sent_ms"] = round(1000 * float(np.median(lat)), 1) if lat else None
    out["per"] = per
    return out


def taps01(hits):
    """HUMAN: the user's kick taps on track 01 (Dark Arm, 54-96 s, tapped on the K3s: best constant shift)."""
    import json
    from label_eval import best_shift
    p = os.path.join(HERE, "annotations", "01_taps_backup_late.json")
    if not os.path.exists(p):
        return ""
    t = np.array(sorted(json.load(open(p, encoding="utf-8"))["kick_add"]))
    t = t[t >= 54]
    hh = hits[(hits >= t.min() - 0.3) & (hits <= t.max() + 0.3)]
    f, sh, pp, r = best_shift(hh, t, 0.0, 0.6, 0.06)
    return f" | HUMAN 01 taps P {pp:.2f} R {r:.2f}"


def fmt(name, m, h):
    return (f"{name:22s} machine kick P/R/F {m['kick'][0]:.2f}/{m['kick'][1]:.2f}/{m['kick'][2]:.2f}  "
            f"kick+snare {m['both'][0]:.2f}/{m['both'][1]:.2f}/{m['both'][2]:.2f}  phantom {m['phantom_per_min']:5.1f}/min "
            f"of {m['hits_per_min']:5.1f}  sent {m['sent_ms']} ms | HUMAN on-marks {h['on_marks']:.2f} caught {h['marks_caught']:.2f} "
            f"F {h['f']:.2f} ({h['hits']} hits)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acts")
    ap.add_argument("--src", default="full")
    ap.add_argument("--lag", type=int, default=3)
    ap.add_argument("--grid", default="0.4:0.9,0.5:0.9,0.4:0.7,0.5:0.7,0.6:0.7,0.5:0.6,0.4:0.6")
    a = ap.parse_args()
    Z = np.load(a.acts)
    nums = [n for n in K.tracks(a.src) if n != K.HUMAN and n in Z]
    FH, kh, sh, t0h, ah, bh = K.load(K.HUMAN, "full")
    for g in a.grid.split(","):
        tk, ts = map(float, g.split(":"))
        hits = {}
        for n in nums:
            t0 = K.load(n, a.src)[3]
            hits[n] = kn_hits(Z[n], t0, a.lag, tk, ts)
        m = machine(hits, nums, a.src)
        h = K.human_score(kn_hits(Z[K.HUMAN], t0h, a.lag, tk, ts)[0])
        print(fmt(f"kicknet k{tk} s{ts}", m, h) + taps01(kn_hits(Z["01"], 0.0, a.lag, tk, ts)[0]), flush=True)


if __name__ == "__main__":
    main()
