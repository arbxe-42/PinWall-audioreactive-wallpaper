"""Old (bench.drum_hits) vs new (stem_labels.label) stem labels, against HUMAN truth only:
  * Adrenaline (14): the user's hand-fixed kick lane 63-127 s (and kick+snare lanes), best constant shift
  * Track 01: the user's notes (no kicks before ~54 s or after ~295 s), their 26 'wrong' marks, and their
    kick taps (made late, with no delay correction: matched at the best constant shift)
  listener/.venv/Scripts/python.exe bench/label_eval.py [k=v label params]
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bench as B  # noqa: E402
import stem_labels as SL  # noqa: E402

FULL = os.path.join(B.MUSIC, "analysis", "full")
P = {kv.split("=")[0]: float(kv.split("=")[1]) for kv in sys.argv[1:] if "=" in kv and "," not in kv} if __name__ == "__main__" else {}


def best_shift(det, truth, lo=-0.1, hi=0.6, tol=0.05):
    best = None
    for sh in np.arange(lo, hi, 0.005):
        m = truth - sh
        p = np.mean([np.min(np.abs(m - h)) <= tol for h in det]) if len(det) else 0
        r = np.mean([np.min(np.abs(det - x)) <= tol for x in m]) if len(det) else 0
        f = 2 * p * r / (p + r + 1e-9)
        if best is None or f > best[0]:
            best = (f, sh, p, r)
    return best


def main():
    x14, sr = B.read_mono(os.path.join(FULL, "14", "drums.flac"))
    x01, sr1 = B.read_mono(os.path.join(FULL, "01", "drums.flac"))
    hk, hs = B.adrenaline_hand_lanes()
    hk = np.array([t for t in hk if 63 <= t <= 127]); hs = np.array([t for t in hs if 63 <= t <= 127])
    a = json.load(open(os.path.join(HERE, "annotations", "01_taps_backup_late.json"), encoding="utf-8"))
    taps = np.array(sorted(a["kick_add"])); wrong = np.array(a["wrong"])
    for name in ("old", "new"):
        if name == "old":
            _, k14, s14 = B.drum_hits(x14, sr); _, k01, s01 = B.drum_hits(x01, sr1)
        else:
            L14 = SL.label(x14, sr, **P); L01 = SL.label(x01, sr1, **P)
            k14, s14, k01, s01 = L14["kicks"], L14["snares"], L01["kicks"], L01["snares"]
        w = lambda arr: arr[(arr >= 62.5) & (arr <= 127.6)]
        f, sh, p, r = best_shift(w(k14), hk)
        both = np.sort(np.concatenate([w(k14), w(s14)]))
        f2, sh2, p2, r2 = best_shift(both, np.sort(np.concatenate([hk, hs])))
        out = (k01 < 53) | (k01 > 296)
        still_wrong = sum(1 for t in wrong if len(k01) and np.min(np.abs(k01 - t)) <= 0.01) + \
            sum(1 for t in wrong if len(s01) and np.min(np.abs(s01 - t)) <= 0.01)
        tt = taps[taps >= 54]
        k01w = k01[(k01 >= 53) & (k01 <= 296)]
        f3, sh3, p3, r3 = best_shift(k01w, tt, 0.0, 0.6, tol=0.06)
        print(f"{name}: ADRENALINE kicks vs your kick lane: {len(w(k14))} labels, P {p:.2f} R {r:.2f} F {f:.2f} (shift {sh*1000:.0f} ms) | "
              f"kick+snare vs your lanes F {f2:.2f} (P {p2:.2f} R {r2:.2f})")
        print(f"     TRACK 01: kicks in the no-kick parts (<53 s, >296 s): {int(out.sum())}; your 'wrong' marks still labelled: "
              f"{still_wrong}/{len(wrong)}; vs your {len(tt)} taps (shift {sh3*1000:.0f} ms): P {p3:.2f} R {r3:.2f}; "
              f"{len(k01w)} kicks labelled 53-296 s")


if __name__ == "__main__":
    main()
