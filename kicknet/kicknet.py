"""KickNet: a tiny causal neural kick (and snare) detector for Pin Wall.

Why: the hand-made rules (low-band spectral flux + dB rise + holds and gates) fire on bass notes,
sidechain swells and vocals. Following the drum-transcription literature (Vogl et al., Southall et al.:
log-filtered spectrogram + its temporal difference, a small network, peak picking), this learns
"is there a kick attack L frames ago?" from the full mix, with labels taken from demucs drum stems of
the user's own tracks. Bass and vocals are in the input but never in the labels, so the network learns
to ignore them.

Everything here is numpy only, so the listener needs no new dependency. The same Features class is
used offline (training, bench) and live (detect.py), so the bench measures exactly what runs live.

Input per frame: the detector's 2048-point magnitude spectrum (10 ms hop).
Features per frame: 40 log-spaced bands (40 Hz - 14 kHz):
  * level: band dB relative to a slow running peak of the whole mix (gain-invariant), scaled
  * d1, d2: band dB change over 1 and 2 frames (the flux, signed)
Context: the last CTX frames, flattened. Model: MLP CTX*120 -> H1 -> H2 -> 2 (kick, snare), sigmoid.
"""
import math
import os

import numpy as np

NB = 40
CTX = 12
F_LO, F_HI = 40.0, 14000.0
REF_DECAY_DB = 0.03       # running peak of the full-mix level falls 3 dB per second
HERE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS = os.path.join(HERE, "kicknet.npz")


def filterbank(sr, nfft):
    """Triangular log-spaced bands over power, each normalised to mean power. (NB, nfft//2+1)"""
    f = np.fft.rfftfreq(nfft, 1.0 / sr)
    bw = sr / nfft
    c = np.geomspace(F_LO, F_HI, NB)
    r = c[1] / c[0]
    W = np.zeros((NB, len(f)), np.float32)
    for i, fc in enumerate(c):
        hw = max(fc * (r - 1.0), 1.2 * bw)
        W[i] = np.clip(1.0 - np.abs(f - fc) / hw, 0.0, None)
        s = W[i].sum()
        if s > 0:
            W[i] /= s
    return W


def _feats_from_levels(L, ref):
    """L: (T, NB) band dB; ref: (T,) running reference dB. Returns (T, 3*NB) per-frame features."""
    lev = np.clip((L - ref[:, None] + 30.0) / 20.0, -2.5, 2.0)
    d1 = np.zeros_like(L); d1[1:] = L[1:] - L[:-1]
    d2 = np.zeros_like(L); d2[2:] = L[2:] - L[:-2]
    d1 = np.clip(d1 / 6.0, -3.0, 3.0)
    d2 = np.clip(d2 / 6.0, -3.0, 3.0)
    return np.concatenate([lev, d1, d2], axis=1).astype(np.float32)


def levels(power, W):
    """power: (..., nbins) -> band dB (..., NB) and full-mix dB (...)."""
    L = 10.0 * np.log10(power @ W.T + 1e-12)
    g = 10.0 * np.log10(power.sum(-1) + 1e-12)
    return L, g


def offline_features(x, sr, nfft=2048):
    """Per-frame features for a mono signal, identical to the streaming path (frame n's window ends
    at sample (n+1)*hop, zero-padded at the start like the live buffer)."""
    hop = int(round(sr / 100.0))
    win = np.hanning(nfft).astype(np.float32)
    wsum = float(win.sum())
    xp = np.concatenate([np.zeros(nfft - hop, np.float32), np.asarray(x, np.float32)])
    nfr = (len(xp) - nfft) // hop + 1
    W = filterbank(sr, nfft)
    Ls, gs = [], []
    for a in range(0, nfr, 4000):
        b = min(nfr, a + 4000)
        idx = np.arange(a, b)[:, None] * hop + np.arange(nfft)[None, :]
        fr = xp[idx] * win
        spec = np.abs(np.fft.rfft(fr, axis=1)) / wsum
        L, g = levels((spec.astype(np.float64)) ** 2, W)
        Ls.append(L); gs.append(g)
    L = np.concatenate(Ls); g = np.concatenate(gs)
    ref = np.empty_like(g)
    r = -60.0
    for i, v in enumerate(g):
        r = max(v, r - REF_DECAY_DB, -60.0)
        ref[i] = r
    return _feats_from_levels(L, ref)


def stack(F, ctx=CTX):
    """(T, D) per-frame features -> (T, ctx*D): frame n sees frames n-ctx+1..n (zeros before 0)."""
    T, D = F.shape
    P = np.concatenate([np.zeros((ctx - 1, D), F.dtype), F])
    idx = np.arange(T)[:, None] + np.arange(ctx)[None, :]
    return P[idx].reshape(T, ctx * D)


class Net:
    """numpy MLP inference. Weights: W1 b1 W2 b2 W3 b3 (+ mu sd for input normalisation)."""

    def __init__(self, path=WEIGHTS):
        z = np.load(path)
        self.w = [z[k].astype(np.float32) for k in ("W1", "b1", "W2", "b2", "W3", "b3")]
        self.mu = z["mu"].astype(np.float32)
        self.sd = z["sd"].astype(np.float32)
        self.lag = int(z["lag"])
        self.ctx = int(z["ctx"]) if "ctx" in z else CTX

    def __call__(self, X):
        W1, b1, W2, b2, W3, b3 = self.w
        h = (X - self.mu) / self.sd
        h = np.maximum(h @ W1 + b1, 0.0)
        h = np.maximum(h @ W2 + b2, 0.0)
        o = h @ W3 + b3
        return 1.0 / (1.0 + np.exp(-o))


class Stream:
    """Live per-frame path: feed the detector's magnitude spectrum, get (kick, snare) activations for
    the attack `net.lag` frames ago."""

    def __init__(self, sr, nfft, net):
        self.W = filterbank(sr, nfft)
        self.net = net
        self.ref = -60.0
        self.Lh = []          # last 3 band-dB rows
        self.hist = np.zeros((net.ctx, 3 * NB), np.float32)

    def push(self, spec):
        power = spec.astype(np.float64) ** 2
        L, g = levels(power, self.W)
        self.ref = max(g, self.ref - REF_DECAY_DB, -60.0)
        self.Lh.append(L)
        if len(self.Lh) > 3:
            self.Lh.pop(0)
        Lm = np.array(([self.Lh[0]] * (3 - len(self.Lh))) + self.Lh) if len(self.Lh) < 3 else np.array(self.Lh)
        # same as _feats_from_levels on the last row (before frame 0 the diffs are zero)
        lev = np.clip((L - self.ref + 30.0) / 20.0, -2.5, 2.0)
        d1 = np.clip((Lm[2] - Lm[1]) / 6.0, -3, 3) if len(self.Lh) >= 2 else np.zeros(NB)
        d2 = np.clip((Lm[2] - Lm[0]) / 6.0, -3, 3) if len(self.Lh) >= 3 else np.zeros(NB)
        f = np.concatenate([lev, d1, d2]).astype(np.float32)
        self.hist = np.roll(self.hist, -1, axis=0)
        self.hist[-1] = f
        a = self.net(self.hist.reshape(1, -1))[0]
        return float(a[0]), float(a[1])
