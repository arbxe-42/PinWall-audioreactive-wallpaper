"""Compare KickNet variants with the LIVE picking rule (thresholds + quiet-stretch guard), on the stem labels
(machine truth, checked by the user by ear) and the user's Dark Arm taps (human truth).

  listener/.venv/Scripts/python.exe bench/kn_compare.py bench/kn_acts_full_lag3_v6.npz [more.npz ...] [--grid 0.5:0.5,0.6:0.6]

Per variant and threshold: P / R / F vs stem kick+snare labels (+-50 ms, one-to-one), hits per minute that land on
no kick/snare label ("off-label", e.g. arps, hats), worst tracks by off-label rate, Dark Arm taps P / R.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kn_train as K  # noqa: E402
from label_eval import best_shift  # noqa: E402


def pick(A, tk, ts, lag=3, gap=9, idle=150, tidle=0.8):
    out, last = [], -10 ** 9
    for n in range(1, len(A)):
        if n - last < gap:
            continue
        q = n - last > idle
        a, b = (max(tk, tidle), max(ts, tidle)) if q else (tk, ts)
        if (A[n, 0] >= a and A[n, 0] >= A[n - 1, 0]) or (A[n, 1] >= b and A[n, 1] >= A[n - 1, 1]):
            out.append(n); last = n
    return (np.array(out) - lag + 1) / 100.0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    grid = sys.argv[sys.argv.index("--grid") + 1] if "--grid" in sys.argv else "0.5:0.5,0.6:0.6,0.7:0.7"
    acts = [a for a in args if a.endswith(".npz")]
    truth = sys.argv[sys.argv.index("--truth") + 1] if "--truth" in sys.argv else "both"
    nums = [n for n in K.tracks("full") if n != K.HUMAN]
    data = {n: K.load(n, "full") for n in nums}
    taps = np.array(sorted(json.load(open(os.path.join(HERE, "annotations", "01_taps_backup_late.json"), encoding="utf-8"))["kick_add"]))
    taps = taps[taps >= 54]
    for f in acts:
        Z = np.load(f)
        for g in grid.split(","):
            tk, ts = map(float, g.split(":"))
            tp = nh = nl = 0; off = 0; dur = 0.0; per = []
            for n in nums:
                F, k, s, t0, a, b = data[n]
                lab = np.sort(k if truth == "kick" else np.concatenate([k, s]))
                tt = pick(Z[n], tk, ts)
                t_, _ = K.match(tt, lab)
                o = sum(1 for t in tt if not len(lab) or np.min(np.abs(lab - t)) > 0.05)
                tp += t_; nh += len(tt); nl += len(lab); off += o; d = (b - a) / 60; dur += d
                per.append((o / d, n))
            p, r = tp / max(1, nh), tp / max(1, nl)
            t1 = pick(Z["01"], tk, ts)
            t1 = t1[(t1 >= taps.min() - 0.3) & (t1 <= taps.max() + 0.3)]
            ff, sh, pp, rr = best_shift(t1, taps, 0.0, 0.6, 0.06)
            worst = ", ".join(f"{n} {v:.0f}" for v, n in sorted(per, reverse=True)[:4])
            print(f"{os.path.basename(f):28s} k{tk} s{ts}: stem {truth} labels P {p:.2f} R {r:.2f} F {2*p*r/(p+r+1e-9):.2f} | "
                  f"off-label {off/dur:5.1f}/min (worst: {worst}) | HUMAN Dark Arm taps P {pp:.2f} R {rr:.2f}", flush=True)


if __name__ == "__main__":
    main()
