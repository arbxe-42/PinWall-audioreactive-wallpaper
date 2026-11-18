"""The human check: the full chain (silent replay -> listener -> the wallpaper's own beat code) on Adrenaline,
scored against the user's hand-fixed kick and snare lanes (music-videos/songs/adrenaline/moments.json,
strength >= 0.5, 44-127 s). The lanes were made while listening on Bluetooth speakers, so they are late by an
unknown constant: instead of assuming it, every shift from 0 to 450 ms is tried and the best one reported.

Run: listener/.venv/Scripts/python.exe tools/e2e_hand.py
"""
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import bench as B  # noqa: E402

PY = os.path.join(ROOT, "listener", ".venv", "Scripts", "python.exe")
OUT = os.path.join(ROOT, "test", "e2e")
START, END = 40.0, 127.0


def main():
    drops = json.load(open(B.DROPS, encoding="utf-8"))
    mix = B.find_mix("14", drops["14"]["file"])
    info, beats = os.path.join(OUT, "hand_info.json"), os.path.join(OUT, "hand_beats.json")
    p = subprocess.Popen([PY, os.path.join(ROOT, "listener", "server.py"), "--replay", mix, "--start", str(START),
                          "--duration", str(END - START), "--port", "4391", "--delay", "0", "--info", info],
                         cwd=os.path.join(ROOT, "listener"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.6)
    subprocess.run(["node", os.path.join(ROOT, "tools", "e2e_beats.mjs"), "4391", beats, str(END - START + 4)], cwd=ROOT)
    p.kill()

    inf = json.load(open(info))
    res = json.load(open(beats))
    hk, hs = B.adrenaline_hand_lanes()
    # hit times -> song seconds (what you hear: replay start + song time + output buffering)
    song = lambda t_ms: START + (t_ms / 1000.0 - inf["t0"] - inf["base_out"])
    hits = np.array([song(h["t"]) for h in res["hits"]])
    hits = hits[(hits >= 63) & (hits <= 127)]
    hk = np.array([t for t in hk if 63 <= t <= 127])
    hs = np.array([t for t in hs if 63 <= t <= 127])
    marks = np.sort(np.concatenate([hk, hs]))

    def score(shift, tol=0.10):   # ±100 ms: your marks were snapped to a cue grid that drifts ~54 ms over the drop
        k = hk - shift
        m = marks - shift
        on_mark = np.array([np.min(np.abs(m - h)) <= tol for h in hits]) if len(hits) else np.array([])
        on_kick = np.array([np.min(np.abs(k - h)) <= tol for h in hits]) if len(hits) else np.array([])
        caught = np.array([np.min(np.abs(hits - x)) <= tol for x in m]) if len(hits) else np.zeros(len(m), bool)
        return on_kick.mean(), on_mark.mean(), caught.mean()

    best = max(np.arange(0.2, 0.601, 0.005), key=lambda s: score(s)[1] + score(s)[2])
    ok, om, cg = score(best)
    errs = []
    for h in hits:
        d = marks - best - h
        j = np.argmin(np.abs(d))
        if abs(d[j]) <= 0.08:
            errs.append(-d[j] * 1000)
    print(f"hits fired in the drop 63-127 s: {len(hits)}   your marked kicks: {len(hk)}   snares: {len(hs)}")
    print(f"best-fitting Bluetooth shift of your marks: {best * 1000:.0f} ms")
    print(f"at that shift: {ok * 100:.0f}% of hits land on one of your kicks (±50 ms), {om * 100:.0f}% on a kick or snare you marked,")
    print(f"               {cg * 100:.0f}% of your marks (kicks + snares) got a hit; timing vs your marks: median {np.median(errs):+.0f} ms")
    for s in ():
        a, b, c = score(s)
        print(f"at a fixed {s * 1000:.0f} ms shift: on your kicks {a * 100:.0f}%, on kick-or-snare {b * 100:.0f}%, marks caught {c * 100:.0f}%")
    # where the misses are: hits not near any mark, by time
    far = [round(h, 2) for h in hits if np.min(np.abs(marks - best - h)) > 0.05]
    print("hits not near any of your marks (song s):", far[:40])
    missed = [round(x + 0, 2) for x in marks if not len(hits) or np.min(np.abs(hits - (x - best))) > 0.05]
    print("your marks with no hit (song s, as marked):", missed[:40])
    json.dump(dict(missed=missed, best_shift=best, on_kick=ok, on_mark=om, caught=cg, far=far), open(os.path.join(OUT, "hand_results.json"), "w"))


if __name__ == "__main__":
    main()
