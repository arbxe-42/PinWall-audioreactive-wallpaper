"""Which hit rule matches the user's own Adrenaline marks best? (human truth: moments.json kick + snare lanes)

Runs the streaming detector over the Adrenaline mix (10-127 s) and scores several rules for what should make
the pictures hit, against the user's marked kicks and snares (strength >= 0.5, 44-127 s). The marks were made
on Bluetooth speakers, so the best constant shift is searched (0-450 ms) for each rule.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "listener"))
import bench as B  # noqa: E402
from detect import Detector, FPS  # noqa: E402

A, Z = 44.0, 127.0
START = 10.0


def run():
    drops = json.load(open(B.DROPS, encoding="utf-8"))
    x, sr = B.read_mono(B.find_mix("14", drops["14"]["file"]), START, Z + 1)
    d = Detector(sr)
    ev = []
    grid = []          # (time of beat, period s, locked, active)
    orig = d._finish_beat

    def fb():
        out = orig()
        grid.append((d.t(d.last_beat) + START, d.P / FPS, d.locked, d.active))
        return out
    d._finish_beat = fb
    for i in range(0, len(x), 1024):
        for e in d.process(x[i:i + 1024]):
            e = dict(e); e["t"] += START
            ev.append(e)
    return ev, grid


def on_grid(t, grid, div=4, frac=0.22):
    """Is t close to a 16th-note position of the beat clock (and was the clock locked)?"""
    g = [b for b in grid if b[0] <= t + 0.2]
    if not g:
        return False
    b0, per, locked, _ = g[-1]
    if not locked:
        return False
    ph = ((t - b0) / (per / div)) % 1.0
    return min(ph, 1 - ph) <= frac


def score(hits, marks, tol=0.05):
    best = None
    for sh in np.arange(0.0, 0.451, 0.005):
        m = marks - sh
        prec = np.mean([np.min(np.abs(m - h)) <= tol for h in hits]) if len(hits) else 0
        rec = np.mean([np.min(np.abs(hits - x)) <= tol for x in m]) if len(hits) else 0
        f = 2 * prec * rec / (prec + rec + 1e-9)
        if best is None or f > best[0]:
            best = (f, sh, prec, rec)
    f, sh, prec, rec = best
    ph = len(hits) * (1 - prec) / ((Z - A) / 60)
    return dict(n=len(hits), shift_ms=round(sh * 1000), on_mark=round(prec, 2), marks_caught=round(rec, 2), f1=round(f, 2),
                phantom_per_min=round(ph, 1))


def main():
    ev, grid = run()
    hk, hs = B.adrenaline_hand_lanes()
    marks = np.sort(np.array([t for t in hk + hs if A <= t <= Z]))
    W = lambda ts: np.array(sorted(t for t in ts if A <= t <= Z))
    groove = W(e["t"] for e in ev if e["type"] in ("kick",))
    kraw = [e for e in ev if e["type"] == "kick_raw"]
    sraw = [e for e in ev if e["type"] == "snare_raw"]
    kok = W(e["t"] for e in kraw if e.get("ok"))
    kok_grid = W(e["t"] for e in kraw if e.get("ok") and on_grid(e["t"], grid))
    zs = np.array([e["z"] for e in sraw]) if sraw else np.array([0])
    zthr = np.percentile(zs, 70)
    snare_grid = W(e["t"] for e in sraw if e["z"] >= zthr and on_grid(e["t"], grid))
    both = np.array(sorted(set(np.round(np.concatenate([kok_grid, snare_grid]), 3))))
    # merge hits closer than 80 ms (one visual hit)
    def merge(a):
        out = []
        for t in a:
            if not out or t - out[-1] > 0.08:
                out.append(t)
        return np.array(out)
    rules = {
        "current: learned kick slots": groove,
        "detected kicks": merge(kok),
        "detected kicks on the 16th grid": merge(kok_grid),
        "kicks + strong snares on the grid": merge(both),
    }
    print(f"your marks 44-127 s: {len(marks)} ({sum(1 for t in hk if A <= t <= Z)} kicks, {sum(1 for t in hs if A <= t <= Z)} snares)")
    for k, v in rules.items():
        print(f"{k:38s}", score(v, marks))


if __name__ == "__main__":
    main()
