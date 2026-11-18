"""Offline test bench for listener/detect.py.

For every drop clip with separated stems, runs the streaming detector on the FULL MIX
(starting 30 s before the 48 s stem window so the clock can settle, like real listening)
and scores it inside the window against ground truth:
  * kicks / snares: onsets found offline (non-causal, careful) on the isolated drum stem
  * Adrenaline also: the user's hand-fixed kick/snare lanes (moments.json, strength >= 0.5),
    shifted by the Bluetooth offset that is measured here first
  * drop: drops_v2.json drop_s

Writes bench/results.json and bench/report.html.

Run:  listener/.venv/Scripts/python.exe bench/bench.py [--quick] [--param k=v ...]
"""
import argparse
import glob
import json
import os
import sys
import time

import numpy as np
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIBE = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "listener"))
from detect import Detector, FPS  # noqa: E402

MUSIC = os.path.join(VIBE, "aesthetic-worlds", "references", "_music", "ultra_ethereal_worlds")
DROPS = os.path.join(MUSIC, "analysis", "drops_v2.json")
ADRENALINE = os.path.join(VIBE, "music-videos", "songs", "adrenaline")
PREROLL = 30.0
MATCH = 0.05  # +-50 ms counts as the same hit


# ---------------------------------------------------------------- audio helpers
def read_mono(path, start=0.0, stop=None):
    info = sf.info(path)
    sr = info.samplerate
    a = int(max(0, start) * sr)
    b = None if stop is None else int(stop * sr)
    x, _ = sf.read(path, start=a, stop=b, dtype="float32", always_2d=True)
    return x.mean(axis=1), sr


def find_mix(num, name):
    p = os.path.join(MUSIC, name)
    if os.path.exists(p):
        return p
    c = sorted(glob.glob(os.path.join(MUSIC, f"{num} - *.wav")))
    return c[0] if c else None


# ---------------------------------------------------------------- ground truth
def _env_onsets(sig, sr, rel, gap_s, rise=0.15, dip=0.4, smooth_ms=5):
    """Attack onsets from a band-limited signal (non-causal, 1 ms resolution).
    Envelope = Hilbert magnitude smoothed over `smooth_ms`. A hit is a local peak above `rel`
    of the clip's loud level that rises out of a real dip (the envelope in the 80 ms before it
    falls under `dip` x peak), so a rolling kick's tail never counts as a new kick. Its time is
    where the envelope last crossed `rise` x peak on the way up: the start of the attack."""
    from scipy.signal import hilbert
    h = sr // 1000
    n = len(sig) // h
    env = np.abs(hilbert(sig[:n * h])).reshape(n, h).mean(1)
    k = max(1, smooth_ms)
    sm = np.convolve(env, np.ones(k) / k, mode="same")
    thr = rel * np.percentile(sm, 99.5)
    out = []
    gap = int(gap_s * 1000)
    i = 1
    while i < n - 1:
        if sm[i] >= thr and sm[i] >= sm[max(0, i - 30):i + 31].max():
            lo = max(0, i - 80)
            if sm[lo:i].min() <= dip * sm[i]:
                j = i
                while j > lo and sm[j] > rise * sm[i]:
                    j -= 1
                if not out or j - out[-1] >= gap:
                    out.append(j)
            i += 20
        else:
            i += 1
    return np.array(out, float) / 1000.0


def _stem_flux(drums, sr, hop_s=0.004, nfft=1024):
    """Spectral flux of a clean drum stem at 4 ms resolution (non-causal analysis)."""
    hop = int(sr * hop_s)
    win = np.hanning(nfft)
    nfr = 1 + (len(drums) - nfft) // hop
    frames = np.lib.stride_tricks.sliding_window_view(drums, nfft)[::hop][:nfr]
    spec = np.abs(np.fft.rfft(frames * win, axis=1)) / win.sum()
    lm = np.log1p(spec * 1000)
    d = np.maximum(lm[1:] - lm[:-1], 0)
    f = np.fft.rfftfreq(nfft, 1 / sr)
    # frame i+1 is centred at (i+1)*hop + nfft/2; a transient shows in the flux as soon as it is
    # inside the louder half of the window: time it a quarter-window after the frame start.
    times = (np.arange(len(d)) + 1) * hop / sr + 0.25 * nfft / sr
    lowdb = 10 * np.log10((spec[1:, f < 150] ** 2).sum(1) + 1e-12)
    return d, f, times, lowdb, hop


def _pick(o, rel, gap_frames):
    thr = rel * np.percentile(o, 99)
    out = []
    for i in range(3, len(o) - 3):
        if o[i] >= thr and o[i] == o[i - 3:i + 4].max():
            if not out or i - out[-1] >= gap_frames:
                out.append(i)
    return np.array(out, int)


def drum_hits(drums, sr):
    """Every drum attack on the stem, labelled kick (low end jumps) or snare (body + snap, no
    low jump). Hats and other light hits stay unlabelled but still count as drum hits."""
    d, f, times, lowdb, hop = _stem_flux(drums, sr)
    full = d[:, (f >= 30)].mean(1)
    idx = _pick(full, 0.18, int(0.06 / (hop / sr)))
    k = int(0.03 / (hop / sr))
    body = d[:, (f >= 150) & (f <= 400)].mean(1)
    snap = d[:, (f >= 1500) & (f <= 8000)].mean(1)
    bthr = np.percentile(body[idx], 50) if len(idx) else 0
    kicks, snares = [], []
    for i in idx:
        a, b = max(0, i - k), min(len(lowdb) - 1, i + k)
        rise = lowdb[b] - lowdb[a]
        if rise >= 6:
            kicks.append(times[i])
        elif body[i] >= bthr and snap[i] >= np.percentile(snap[idx], 50):
            snares.append(times[i])
    return times[idx], np.array(kicks), np.array(snares)


def stem_onsets(drums, sr):
    _, k, s = drum_hits(drums, sr)
    return k, s


def any_drum_onsets(drums, sr):
    return drum_hits(drums, sr)[0]


def match(det, truth, tol=MATCH):
    """Greedy one-to-one matching. Returns matched pairs (d, t), unmatched det, unmatched truth."""
    det, truth = np.sort(np.asarray(det, float)), np.sort(np.asarray(truth, float))
    used = np.zeros(len(truth), bool)
    pairs, extra = [], []
    for d in det:
        if len(truth) == 0:
            extra.append(d)
            continue
        j = int(np.searchsorted(truth, d))
        best = None
        for k in (j - 1, j):
            if 0 <= k < len(truth) and not used[k] and abs(truth[k] - d) <= tol:
                if best is None or abs(truth[k] - d) < abs(truth[best] - d):
                    best = k
        if best is None:
            extra.append(d)
        else:
            used[best] = True
            pairs.append((d, truth[best]))
    return pairs, extra, list(truth[~used])


TRUTH_LAG = 0.0  # set by calibrate(): constant lag of waveform truth vs perceived attack


def score_hits(det, truth, dur_min):
    truth = np.asarray(truth, float) - TRUTH_LAG
    pairs, extra, miss = match(det, truth)
    errs = np.array([d - t for d, t in pairs]) * 1000 if pairs else np.array([])
    return dict(
        truth=len(truth), det=len(det), hit=len(pairs),
        recall=round(len(pairs) / max(1, len(truth)), 3),
        precision=round(len(pairs) / max(1, len(det)), 3),
        phantom_per_min=round(len(extra) / dur_min, 2),
        err_mean_ms=round(float(errs.mean()), 1) if len(errs) else None,
        err_abs_ms=round(float(np.abs(errs).mean()), 1) if len(errs) else None,
        phantoms=[round(x, 3) for x in extra], misses=[round(x, 3) for x in miss],
    )


# ---------------------------------------------------------------- run one clip
def run_detector(x, sr, params=None, t0=0.0):
    det = Detector(sr, params=params)
    events = []
    B = 1024
    for i in range(0, len(x), B):
        for e in det.process(x[i:i + B]):
            e = dict(e)
            e["t"] = round(e["t"] + t0, 4)
            events.append(e)
    return events


def bluetooth_offset(hand, stem_kicks):
    """Constant delay of the hand lanes vs the stem onsets (positive = taps late)."""
    best, best_d = -1, 0.0
    for d in np.arange(-0.6, 0.601, 0.002):
        c = len(match(np.asarray(hand) - d, stem_kicks, tol=0.03)[0])
        if c > best:
            best, best_d = c, d
    return round(float(best_d), 3), best, len(hand)


def run_clip(num, meta, params, adrenaline_hand=None):
    mix = find_mix(num, meta["file"])
    stem = os.path.join(MUSIC, "analysis", "drop", num, "stems", "drums.flac")
    w0, w1 = meta["window"]
    drums, sr = read_mono(stem)
    tk, ts = stem_onsets(drums, sr)
    tk, ts = tk + w0, ts + w0
    x, sr2 = read_mono(mix, w0 - PREROLL, w1)
    t0 = max(0.0, w0 - PREROLL)
    t_start = time.perf_counter()
    events = run_detector(x, sr2, params, t0=t0)
    cpu = time.perf_counter() - t_start
    inwin = [e for e in events if w0 <= e["t"] <= w1]
    dur_min = (w1 - w0) / 60

    def times(kind):
        return [e["t"] for e in inwin if e["type"] == kind]

    beats = [e for e in events if e["type"] == "beat"]
    beats_in = [e for e in beats if w0 <= e["t"] <= w1]
    locked_in = [e for e in beats_in if e["locked"]]
    first_lock = next((e["t"] for e in beats if e["locked"] and e["t"] >= w0 - 8), None)
    bpm_est = float(np.median([e["bpm"] for e in locked_in])) if locked_in else None
    true_bpm = meta.get("drums", {}).get("tempo_bpm")
    tempo_ok, tempo_oct = None, None
    if bpm_est and true_bpm:
        r = bpm_est / true_bpm
        tempo_ok = abs(r - 1) < 0.04
        tempo_oct = any(abs(r - m) / m < 0.04 for m in (0.5, 1, 2, 2 / 3, 1.5))
    drops = [e["t"] for e in events if e["type"] == "drop" and w0 - 10 <= e["t"] <= w1]
    drop_hit = any(abs(d - meta["drop_s"]) <= 1.0 for d in drops)  # truth is rounded to whole seconds

    allhits = np.sort(np.concatenate([tk, ts, any_drum_onsets(drums, sr) + w0]))
    lb = np.array([e["t"] for e in locked_in])
    if len(lb) and len(allhits):
        dd = np.array([b - allhits[np.argmin(np.abs(allhits - b))] for b in lb])
        on = np.abs(dd) <= MATCH
        beat_on = round(float(on.mean()), 3)
        beat_err = round(float(np.median(dd[on]) * 1000), 1) if on.any() else None
    else:
        beat_on, beat_err = None, None
    res = dict(
        num=num, title=os.path.basename(mix)[:-4], window=[w0, w1], drop_true=meta["drop_s"],
        beat_on_drum=beat_on, beat_err_ms=beat_err,
        cpu_x_realtime=round(cpu / (len(x) / sr2), 4),
        kick=score_hits(times("kick"), tk, dur_min),
        kick_raw=score_hits(times("kick_raw"), tk, dur_min),
        snare=score_hits(times("snare"), ts, dur_min),
        snare_raw=score_hits(times("snare_raw"), ts, dur_min),
        bpm_est=bpm_est, bpm_true=true_bpm, tempo_exact=tempo_ok, tempo_octave=tempo_oct,
        lock_after_s=None if first_lock is None else round(first_lock - w0, 2),
        locked_frac=round(len(locked_in) / max(1, len(beats_in)), 3),
        drops=[round(d, 2) for d in drops], drop_hit=drop_hit,
        false_drops=sum(1 for d in drops if abs(d - meta["drop_s"]) > 1.0),
        truth_kick=[round(t, 3) for t in tk], truth_snare=[round(t, 3) for t in ts],
        drum_hits=[round(float(t), 3) for t in allhits],
        fired_kick=[round(t, 3) for t in times("kick")], fired_snare=[round(t, 3) for t in times("snare")],
        beats=[[e["t"], int(e["locked"]), e.get("accent", 0)] for e in beats_in],
    )
    if adrenaline_hand is not None:
        hk, hs, off = adrenaline_hand
        a, b = max(w0, 44.0), min(w1, 127.0)
        hk_w = [t - off for t in hk if a <= t - off <= b]
        hs_w = [t - off for t in hs if a <= t - off <= b]
        dm = (b - a) / 60
        res["hand"] = dict(
            offset_s=off, window=[a, b],
            kick=score_hits([t for t in times("kick") if a <= t <= b], hk_w, dm),
            snare=score_hits([t for t in times("snare") if a <= t <= b], hs_w, dm),
            truth_kick=[round(t, 3) for t in hk_w], truth_snare=[round(t, 3) for t in hs_w],
        )
    return res


def adrenaline_hand_lanes():
    m = json.load(open(os.path.join(ADRENALINE, "moments.json"), encoding="utf-8"))
    hk = [t for t, s in m["drums"]["kick"] if s >= 0.5]
    hs = [t for t, s in m["drums"]["snare"] if s >= 0.5]
    return hk, hs


def summarise(results):
    def agg(key, sub):
        rs = [r[key] for r in results]
        tot_t = sum(r["truth"] for r in rs)
        tot_h = sum(r["hit"] for r in rs)
        mins = sum((r_["window"][1] - r_["window"][0]) / 60 for r_ in results)
        ph = sum(len(r["phantoms"]) for r in rs) / mins
        errs = [r["err_abs_ms"] for r in rs if r["err_abs_ms"] is not None]
        tot_d = sum(r["det"] for r in rs)
        return dict(recall=round(tot_h / max(1, tot_t), 3), precision=round(tot_h / max(1, tot_d), 3),
                    phantom_per_min=round(ph, 2),
                    err_abs_ms=round(float(np.mean(errs)), 1) if errs else None)

    s = {k: agg(k, None) for k in ("kick", "kick_raw", "snare", "snare_raw")}
    bo = [r["beat_on_drum"] for r in results if r["beat_on_drum"] is not None]
    be = [r["beat_err_ms"] for r in results if r["beat_err_ms"] is not None]
    s["beat_on_drum"] = round(float(np.mean(bo)), 3) if bo else None
    s["beat_err_ms_median"] = round(float(np.median(be)), 1) if be else None
    s["tempo_exact"] = sum(1 for r in results if r["tempo_exact"]) / len(results)
    s["tempo_octave"] = sum(1 for r in results if r["tempo_octave"]) / len(results)
    locks = [r["lock_after_s"] for r in results if r["lock_after_s"] is not None]
    s["locked_frac"] = round(float(np.mean([r["locked_frac"] for r in results])), 3)
    s["never_locked"] = sum(1 for r in results if r["lock_after_s"] is None)
    s["drop_hit"] = sum(1 for r in results if r["drop_hit"])
    s["false_drops"] = sum(r["false_drops"] for r in results)
    s["clips"] = len(results)
    s["cpu_x_realtime"] = round(float(np.mean([r["cpu_x_realtime"] for r in results])), 4)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="first 8 clips only")
    ap.add_argument("--only", default=None, help="comma list of clip numbers")
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--out", default=os.path.join(ROOT, "bench", "results.json"))
    a = ap.parse_args()
    params = {}
    for kv in a.param:
        k, v = kv.split("=")
        params[k] = float(v)
    drops = json.load(open(DROPS, encoding="utf-8"))
    nums = [n for n in drops if find_mix(n, drops[n]["file"])]
    if a.only:
        nums = [n for n in nums if n in a.only.split(",")]
    if a.quick:
        nums = nums[:8]

    # Bluetooth offset of the hand lanes, measured against the Adrenaline drum stem over the
    # whole hand-edited range (stem windows only cover 55-103 s, so use the full-song stem).
    # Calibrate the constant lag between the waveform truth and the detector's raw kick onsets
    # (median over clips, nearest pairs within 80 ms). One number for all clips, reported.
    global TRUTH_LAG
    measured = 0.0
    lags = []
    for n in nums[:12]:
        m = drops[n]
        w0, w1 = m["window"]
        dr, sr = read_mono(os.path.join(MUSIC, "analysis", "drop", n, "stems", "drums.flac"))
        tk, _ = stem_onsets(dr, sr)
        tk = tk + w0
        x, sr2 = read_mono(find_mix(n, m["file"]), w0 - 10, w1)
        ev = run_detector(x, sr2, params, t0=w0 - 10)
        dk = np.array([e["t"] for e in ev if e["type"] == "kick_raw" and w0 <= e["t"] <= w1])
        for t in tk:
            if len(dk):
                d = dk[np.argmin(np.abs(dk - t))] - t
                if abs(d) < 0.08:
                    lags.append(d)
    measured = -float(np.median(lags)) if lags else 0.0
    TRUTH_LAG = 0.0  # not applied: the detector bias is tuned so this reads ~0
    print(f"detector raw kicks vs truth attack: {-measured * 1000:+.1f} ms median (from {len(lags)} kicks)")

    hk, hs = adrenaline_hand_lanes()
    full_stem = os.path.join(ADRENALINE, "stems", "drums.flac")
    d, sr = read_mono(full_stem)
    sk, _ = stem_onsets(d, sr)
    off, matched, n_hand = bluetooth_offset(hk, sk)
    print(f"hand kick lane offset vs drum stem: {off * 1000:+.0f} ms ({matched}/{n_hand} kicks line up)")

    results = []
    for n in nums:
        hand = (hk, hs, off) if n == "14" else None
        r = run_clip(n, drops[n], params, hand)
        results.append(r)
        k, s = r["kick"], r["snare"]
        print(f"{n} {r['title'][:34]:34s} bpm {r['bpm_est']}/{r['bpm_true']} lock {r['lock_after_s']} "
              f"lockfrac {r['locked_frac']:.2f} beat_on {r['beat_on_drum']} err {r['beat_err_ms']} | kick rec {k['recall']:.2f} prec {k['precision']:.2f} ph/min {k['phantom_per_min']:.1f} "
              f"err {k['err_abs_ms']} | snare rec {s['recall']:.2f} ph/min {s['phantom_per_min']:.1f} | "
              f"drop {'Y' if r['drop_hit'] else 'n'} false {r['false_drops']}")
    summ = summarise(results)
    summ["hand_offset_s"] = off
    summ["raw_kick_vs_truth_ms"] = round(-measured * 1000, 1)
    summ["hand_offset_matched"] = [matched, n_hand]
    summ["params"] = params
    print(json.dumps(summ, indent=1))
    json.dump(dict(summary=summ, results=results), open(a.out, "w"), indent=0)


if __name__ == "__main__":
    main()
