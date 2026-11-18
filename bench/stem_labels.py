"""Kick / snare / hat labels from a clean drum stem (offline, zero-phase, 1 ms resolution).

v2 (2026-11-18), after the user checked the v1 labels by ear: "the drum stem is really good, but the labels
miss a ton or mark kicks where there are none; just look at the bass hits". v1 (bench.drum_hits) picked any
drum onset and called it a kick when the low end rose 6 dB, with no absolute level, so faint low-end flutter
under hi-hats (40-70 dB below the real kicks) counted as kicks.

Kick  = a FAST low-end attack (30-150 Hz energy rises >= rise_db within 20 ms) whose peak is LOUD
        (within gate_db of the track's real kicks: the 99.5th percentile of the low band).
Snare = a STRONG attack in the snap band (1.5-7 kHz rises >= 22 dB in 40 ms) together with a body attack
        (150-600 Hz), loud vs the track's snares, ringing >= 8 ms (not a click), not on a kick (a kick+snare
        hit is a kick). Tightened after the user: "you are spamming snares" (soft percussion rose only 12-20 dB).
Hat   = a fast attack in 7-16 kHz that is neither.
Tuned on human truth (bench/label_eval.py): Adrenaline vs the user's kick lane P .58 R .88 (v1: .25 / .52; most
remaining "extras" are one drum roll the user didn't mark), track 01 vs the user's taps P .94 R .95, 3 kicks
in the parts they said have none (v1: 55).
Times = the start of the attack: where the band envelope first gets halfway (in dB) from the pre-attack
        floor to the peak.
"""
import numpy as np
from scipy.signal import butter, sosfiltfilt

MS = 1000  # envelope rate: frames of sr // 1000 samples (~1 ms; times are converted exactly)


def _env_db(x, sr, lo, hi, smooth_ms=4):
    sos = butter(4, [lo, hi] if hi else lo, 'band' if hi else 'high', fs=sr, output='sos')
    y = sosfiltfilt(sos, x)
    h = sr // MS
    n = len(y) // h
    e = (y[:n * h] ** 2).reshape(n, h).mean(1)
    k = max(1, smooth_ms)
    e = np.convolve(e, np.ones(k) / k, mode='same')
    return 10 * np.log10(e + 1e-14)


def _attacks(L, rise_db, gate, win=20, gap=45, look=30):
    """Fast rises: r[t] = L[t] - min(L[t-win:t]); local maxima of r with r >= rise_db and a peak level
    (max of L over the next `look` ms) >= gate. Returns (attack start index, peak level) pairs."""
    n = len(L)
    from numpy.lib.stride_tricks import sliding_window_view
    P = np.concatenate([np.full(win, L[0]), L])
    mins = sliding_window_view(P, win + 1).min(1)[:n]
    r = L - mins
    Q = np.concatenate([L, np.full(look, L[-1])])
    peaks = sliding_window_view(Q, look + 1).max(1)[:n]
    cand = np.where((r >= rise_db) & (peaks >= gate))[0]
    out = []
    i = 0
    while i < len(cand):
        # group consecutive candidate samples into one rise; take the sample where r is largest
        j = i
        while j + 1 < len(cand) and cand[j + 1] - cand[j] <= 3:
            j += 1
        seg = cand[i:j + 1]
        t = int(seg[np.argmax(r[seg])])
        # attack start: halfway (dB) from the pre-attack floor to the peak, searched backwards
        floor = mins[t]
        pk = peaks[t]
        half = floor + 0.5 * (pk - floor)
        a = t
        lo = max(0, t - win - 10)
        while a > lo and L[a - 1] >= half:
            a -= 1
        # move forward if we are still below half (peak comes after t)
        b = a
        while b < min(n - 1, t + look) and L[b] < half:
            b += 1
        start = b
        if not out or start - out[-1][0] >= gap:
            out.append((start, float(pk)))
        elif pk > out[-1][1]:
            out[-1] = (start, float(pk))
        i = j + 1
    return out


def label(x, sr, gate_db=14.0, rise_db=15.0, snare_gate_db=20.0, hat_gate_db=26.0, kick_win=40,
          snare_rise_db=22.0, snare_min_ms=8, click_rel_db=28.0, crise_rel_db=15.0, big_db=4.0, big_rise_db=12.0, double_ms=100, double_dip_db=12.0, balance_db=-99.0, merge_ms=70, body_rel_db=99.0, subonly_db=-12.0):
    Lk = _env_db(x, sr, 30, 150)
    Lb = _env_db(x, sr, 150, 600)
    Ls = _env_db(x, sr, 1500, 7000)
    Lh = _env_db(x, sr, 7000, min(16000, sr / 2 - 100))
    ref_k = np.percentile(Lk, 99.5)
    kicks = _attacks(Lk, rise_db, ref_k - gate_db, win=int(kick_win), gap=45)
    # A track's kicks are one sample, so they share a click: the high band (2-10 kHz) at the attack. Low thumps
    # whose click is far under the track's typical kick click (bass bleeding into the stem, e.g. Adrenaline's
    # intro) are not kicks. Relative per track, so soft clickless kicks (track 02) still count.
    Lc = _env_db(x, sr, 2000, 10000)
    if kicks:
        cl = np.array([Lc[a:a + 15].max() for a, _ in kicks])
        pks = np.array([pk for _, pk in kicks])
        strong = pks >= ref_k - 6.0
        typical = np.median(cl[strong]) if strong.sum() >= 8 else np.median(cl)
        # ...and the click RISES like the track's kicks do: synth leads and bass bleeding into the stem start
        # softly (Adrenaline 2:45-2:56: +2..10 dB vs +21..29 dB for its real kicks)
        cr = np.array([Lc[a:a + 15].max() - Lc[max(0, a - 40):a].min() for a, _ in kicks])
        typ_r = np.median(cr[strong]) if strong.sum() >= 8 else np.median(cr)
        kicks = [k for k, c, r in zip(kicks, cl, cr) if c >= typical - click_rel_db and r >= typ_r - crise_rel_db]
    # A kick's weight is in the sub (30-110 Hz). Bass lines that bleed into the stem hit 120-250 Hz with a weak
    # sub (Saint or Sinner: the user tapped 1 of ~20 such hits). Each band is measured against the track's own
    # loudest level, so the rule adapts per track.
    Lsub = _env_db(x, sr, 30, 110)
    Lmb = _env_db(x, sr, 120, 250)
    rsub, rmb = np.percentile(Lsub, 99.5), np.percentile(Lmb, 99.5)
    kicks = [(a, pk) for a, pk in kicks if (Lsub[a:a + 30].max() - rsub) - (Lmb[a:a + 30].max() - rmb) >= balance_db]
    # Pure sub notes are not kicks: a kick's transient always spreads into 110-250 Hz, a sub-bass note (or an
    # arp in the sub) barely does. 825 hp: every hit the user marked wrong had 110-250 Hz 15-28 dB UNDER the
    # 30-70 Hz sub at the attack; its real kicks 15-23 dB above.
    S70 = _env_db(x, sr, 30, 70)
    M250 = _env_db(x, sr, 110, 250)
    if kicks:
        kicks = [(a, pk) for a, pk in kicks if M250[a:a + 30].max() - S70[a:a + 30].max() >= subonly_db]
    # A kick has body: 250 Hz - 2 kHz at its attack close to the track's loud kicks (75th percentile of the
    # strong candidates, so a pure-sub sound that alternates with the kicks can't drag the reference down).
    # Pure sub hits are bass/arp notes left in the stem (825 hp drop, 1:31-1:34: the off-beat "kicks" had
    # 250 Hz-2 kHz 17-24 dB under the real kicks).
    if kicks:
        Lmid = _env_db(x, sr, 250, 2000)
        mids = np.array([Lmid[a:a + 30].max() for a, _ in kicks])
        pk2 = np.array([pk for _, pk in kicks])
        strong2 = pk2 >= ref_k - 6.0
        ref_mid = np.percentile(mids[strong2], 75) if strong2.sum() >= 8 else np.percentile(mids, 75)
        kicks = [k for k, m in zip(kicks, mids) if m >= ref_mid - body_rel_db]
    # one kick, not two: a second attack within double_ms only counts when the low end dipped in between
    # (user, 825 hp: "random doubles right next to each other which should be 1")
    merged = []
    for a, pk in kicks:
        if merged and a - merged[-1][0] < merge_ms:
            continue   # layered kicks (neurotransmission: a short attack, then the body 52 ms later) are one kick
        if merged and a - merged[-1][0] < double_ms:
            p0 = merged[-1][0]
            top = p0 + int(np.argmax(Lk[p0:a + 1]))          # the first kick's peak
            dip = min(merged[-1][1], pk) - Lk[top:a + 1].min()  # how far the low end fell before the second
            if dip < double_dip_db:
                continue
        merged.append((a, pk))
    kicks = merged
    kt = np.array([a for a, _ in kicks], float)
    # snares: body and snap attacks that coincide (within 15 ms)
    ref_b, ref_s = np.percentile(Lb, 99.5), np.percentile(Ls, 99.5)
    body = np.array([a for a, _ in _attacks(Lb, 12.0, ref_b - snare_gate_db, win=40, gap=60)], float)
    snap = np.array([a for a, _ in _attacks(Ls, snare_rise_db, ref_s - snare_gate_db, win=40, gap=60)], float)
    snares = []
    for s in snap:
        if not (len(body) and np.min(np.abs(body - s)) <= 15) or (len(kt) and np.min(np.abs(kt - s)) <= 20):
            continue
        # a snare rings: its snap band stays within 12 dB of its peak for a while (clicks and ticks die in ~3 ms)
        i = int(s); seg = Ls[i:i + 400]
        m = int(np.argmax(seg[:40])) if len(seg) else 0
        tail = seg[m:] < seg[m] - 12 if len(seg) else np.array([True])
        if (int(np.argmax(tail)) if tail.any() else 400) < snare_min_ms:
            continue
        snares.append(s)
    st = np.array(snares, float)
    # Big hits: the user reads the stem by eye ("all the big hits are clearly either a kick or snare"). Any
    # broadband attack within big_db of the stem's loudest hits is a hit: a kick when the low end carries it
    # (within gate_db of the real kicks), else a snare. Catches strong snares the snap rule misses.
    Lf = _env_db(x, sr, 30, min(16000, sr / 2 - 100))
    ref_f = np.percentile(Lf, 99.5)
    for a, _ in _attacks(Lf, big_rise_db, ref_f - big_db, win=40, gap=60):
        if (len(kt) and np.min(np.abs(kt - a)) <= double_ms) or (len(st) and np.min(np.abs(st - a)) <= 25):
            continue
        if Lk[a:a + 40].max() >= ref_k - gate_db:
            if subonly_db > -90 and M250[a:a + 30].max() - S70[a:a + 30].max() < subonly_db:
                continue   # a loud pure sub note, not a kick (see above)
            kt = np.sort(np.append(kt, a))
        else:
            st = np.sort(np.append(st, a))
    ref_h = np.percentile(Lh, 99.5)
    hats = []
    for h, _ in _attacks(Lh, rise_db, ref_h - hat_gate_db, gap=35):
        near_k = len(kt) and np.min(np.abs(kt - h)) <= 20
        near_s = len(st) and np.min(np.abs(st - h)) <= 20
        if not near_k and not near_s:
            hats.append(h)
    ht = np.array(hats, float)
    allo = np.sort(np.concatenate([kt, st, ht]))
    fp = (sr // MS) / sr   # one envelope frame in seconds (44 samples at 44.1 kHz = 0.998 ms, not 1 ms)
    return {"kicks": kt * fp, "snares": st * fp, "hats": ht * fp, "onsets": allo * fp}
