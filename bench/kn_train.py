"""Train and score KickNet (listener/kicknet.py) on the user's tracks.

Data: each track's full mix -> features; its demucs drum stem -> kick / snare onsets (stem_labels.label, v2,
checked against the user's ears and marks; still stem-derived "machine truth", not human). Adrenaline (14) is NEVER trained on:
it is kept for the human check against the user's hand marks.

Scoring (all held out):
  * machine truth: 5-fold cross-validation by track; every track is scored by a model that never saw it
  * human truth: Adrenaline 63-127 s vs the user's kick + snare lanes, best constant shift, +-100 ms
    (same as bench/hand_fast.py)

Run with the music pipeline venv (torch):
  aesthetic-worlds/references/_music/pipeline/.venv/Scripts/python.exe live-wallpaper/bench/kn_train.py [--src full|drop] [--lag 3] [--export]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "listener"))
import bench as B  # noqa: E402
import kicknet as KN  # noqa: E402
import stem_labels as SL  # noqa: E402

LABELS = 7   # stem labeller version (1 = bench.drum_hits, 2-7 = stem_labels.label; 7 = + pure-sub notes are not kicks; tuned on human marks 2026-11-18)

FPS = 100.0
CACHE = os.path.join(HERE, "kn_cache")
FULL = os.path.join(B.MUSIC, "analysis", "full")
HUMAN = "14"


def tracks(src):
    drops = json.load(open(B.DROPS, encoding="utf-8"))
    out = []
    if src == "full":
        for num in sorted(os.listdir(FULL)):
            if os.path.exists(os.path.join(FULL, num, "drums.flac")):
                out.append(num)
    else:
        out = sorted(drops)
    return out


ALLH = {}


def _save(cp, **arrs):
    """Write the cache atomically (a run stopped mid-write must not leave a broken file)."""
    tmp = cp + ".tmp.npz"
    np.savez_compressed(tmp, **arrs)
    os.replace(tmp, cp)


def stem_path(num, src):
    if src == "full":
        return os.path.join(FULL, num, "drums.flac")
    return os.path.join(B.MUSIC, "analysis", "drop", num, "stems", "drums.flac")


def load(num, src):
    """Per-frame features (T, 120) float16, kick / snare onset times (s, mix time), frame time offset."""
    os.makedirs(CACHE, exist_ok=True)
    cp = os.path.join(CACHE, f"{src}_{num}.npz")
    if os.path.exists(cp):
        z = np.load(cp)
        if (int(z["lv"]) if "lv" in z else 1) < LABELS:   # labels from an older labeller: redo them (features stay)
            st, ssr = B.read_mono(stem_path(num, src))
            lab = SL.label(st, ssr)
            off = 0.0 if src == "full" else json.load(open(B.DROPS, encoding="utf-8"))[num]["window"][0]
            z = dict(z); z.update(k=lab["kicks"] + off, s=lab["snares"] + off, h=lab["onsets"] + off, lv=LABELS)
            _save(cp, **z)
        ALLH[(num, src)] = np.asarray(z["h"])
        return z["F"], z["k"], z["s"], float(z["t0"]), float(z["a"]), float(z["b"])
    drops = json.load(open(B.DROPS, encoding="utf-8"))
    meta = drops.get(num)
    import glob
    mixp = B.find_mix(num, meta["file"]) if meta else sorted(glob.glob(os.path.join(B.MUSIC, f"{num} - *.wav")))[0]
    if src == "full":
        st, ssr = B.read_mono(os.path.join(FULL, num, "drums.flac"))
        x, sr = B.read_mono(mixp)
        t0, a, b = 0.0, 0.0, len(x) / sr
        off = 0.0
    else:
        w0, w1 = meta["window"]
        st, ssr = B.read_mono(os.path.join(B.MUSIC, "analysis", "drop", num, "stems", "drums.flac"))
        t0 = max(0.0, w0 - 20)
        x, sr = B.read_mono(mixp, t0, w1)
        a, b = w0, w1
        off = w0
    lab = SL.label(st, ssr)
    allh, kicks, snares = lab["onsets"], lab["kicks"], lab["snares"]
    F = KN.offline_features(x, sr).astype(np.float16)
    _save(cp, F=F, k=kicks + off, s=snares + off, h=allh + off, t0=t0, a=a, b=b, lv=LABELS)
    ALLH[(num, src)] = allh + off
    return F, kicks + off, snares + off, t0, a, b


def targets(T, times, t0, lag):
    y = np.zeros(T, np.float32)
    for t in times:
        n = int(np.ceil((t - t0) * FPS - 1.0)) + lag
        for dn, v in ((-1, 0.3), (0, 1.0), (1, 0.6)):
            if 0 <= n + dn < T:
                y[n + dn] = max(y[n + dn], v)
    return y


# ------------------------------------------------------------------ scoring
def pick(a, thr, gap=9):
    """Causal trigger: fire on frame n when the activation is at least thr and still rising."""
    out, last = [], -10 ** 9
    for n in range(1, len(a)):
        if a[n] >= thr and a[n] >= a[n - 1] and n - last >= gap:
            out.append(n); last = n
    return np.array(out, int)


def match(det, truth, tol=0.05):
    """One-to-one greedy match. Returns (true positives, errors det-truth)."""
    if not len(det) or not len(truth):
        return 0, []
    used = np.zeros(len(truth), bool); tp = 0; err = []
    for t in det:
        j = np.searchsorted(truth, t)
        best = None
        for c in (j - 1, j):
            if 0 <= c < len(truth) and not used[c] and abs(truth[c] - t) <= tol:
                if best is None or abs(truth[c] - t) < abs(truth[best] - t):
                    best = c
        if best is not None:
            used[best] = True; tp += 1; err.append(t - truth[best])
    return tp, err


def human_score(hits):
    hk, hs = B.adrenaline_hand_lanes()
    marks = np.array(sorted(t for t in hk + hs if 63 <= t <= 127))
    hits = np.array([h for h in hits if 63 <= h <= 127])
    best = None
    for sh in np.arange(0.2, 0.6, 0.005):
        m = marks - sh
        p = np.mean([np.min(np.abs(m - h)) <= 0.1 for h in hits]) if len(hits) else 0
        r = np.mean([np.min(np.abs(hits - x_)) <= 0.1 for x_ in m]) if len(hits) else 0
        f = 2 * p * r / (p + r + 1e-9)
        if best is None or f > best[0]:
            best = (f, sh, p, r)
    return dict(hits=len(hits), on_marks=round(best[2], 3), marks_caught=round(best[3], 3), f=round(best[0], 3))


# ------------------------------------------------------------------ training
def train(data, lag, epochs, seed=0, h1=128, h2=64, ctx=KN.CTX, log=None, kick_only=False):
    import torch
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    D = 3 * KN.NB
    Fs, Ys, idx = [], [], []
    off = 0
    for F, k, s, t0, a, b in data:
        T = len(F)
        pad = np.zeros((ctx - 1, D), np.float32)
        Fs.append(pad); off += ctx - 1
        Fs.append(F.astype(np.float32))
        y = np.stack([targets(T, k, t0, lag), targets(T, s, t0, lag)], 1)
        Ys.append(np.zeros((ctx - 1, 2), np.float32)); Ys.append(y)
        n = np.arange(T); tt = t0 + n / FPS
        keep = n[(tt >= a) & (tt <= b)]
        idx.append(keep + off)
        off += T
    Fa = torch.from_numpy(np.concatenate(Fs)); Ya = torch.from_numpy(np.concatenate(Ys))
    idx = np.concatenate(idx)
    mu = Fa[torch.from_numpy(idx)].mean(0).numpy(); sd = Fa[torch.from_numpy(idx)].std(0).numpy() + 1e-3
    mu_t = torch.from_numpy(np.tile(mu, ctx)); sd_t = torch.from_numpy(np.tile(sd, ctx))
    net = torch.nn.Sequential(torch.nn.Linear(ctx * D, h1), torch.nn.ReLU(), torch.nn.Dropout(0.25),
                              torch.nn.Linear(h1, h2), torch.nn.ReLU(), torch.nn.Linear(h2, 2))
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-3)
    ar = torch.arange(ctx) - (ctx - 1)
    bs = 1024
    steps = epochs * len(idx) // bs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-3, total_steps=steps)
    posw = torch.tensor([4.0, 4.0])
    band = (torch.arange(KN.NB).float() - KN.NB / 2) / (KN.NB / 2)
    net.train()
    for st in range(steps):
        bi = torch.from_numpy(rng.choice(idx, bs))
        X = Fa[bi[:, None] + ar[None, :]]            # (bs, ctx, D)
        # augmentation: overall level offset and spectral tilt (+-6 dB), applied to the level features
        g = (torch.rand(bs, 1, 1) - 0.5) * 0.6
        tilt = (torch.rand(bs, 1, 1) - 0.5) * 0.6
        X[:, :, :KN.NB] = X[:, :, :KN.NB] + g + tilt * band
        X = (X.reshape(bs, -1) - mu_t) / sd_t
        y = Ya[bi]
        o = net(X)
        if kick_only:   # the user: "a lot of kicks are snares too ... train kicknet to just get the kicks"
            loss = torch.nn.functional.binary_cross_entropy_with_logits(o[:, 0], y[:, 0], pos_weight=posw[0])
        else:
            loss = torch.nn.functional.binary_cross_entropy_with_logits(o, y, pos_weight=posw)
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        if log and st % 1000 == 0:
            print(f"  step {st}/{steps} loss {loss.item():.4f}", flush=True)
    net.eval()
    L = [m for m in net if isinstance(m, torch.nn.Linear)]
    w = {"W1": L[0].weight.detach().numpy().T, "b1": L[0].bias.detach().numpy(),
         "W2": L[1].weight.detach().numpy().T, "b2": L[1].bias.detach().numpy(),
         "W3": L[2].weight.detach().numpy().T, "b3": L[2].bias.detach().numpy(),
         "mu": np.tile(mu, ctx), "sd": np.tile(sd, ctx), "lag": lag, "ctx": ctx}
    return w


class NumpyNet(KN.Net):
    def __init__(self, w):
        self.w = [np.asarray(w[k], np.float32) for k in ("W1", "b1", "W2", "b2", "W3", "b3")]
        self.mu = np.asarray(w["mu"], np.float32); self.sd = np.asarray(w["sd"], np.float32)
        self.lag = int(w["lag"]); self.ctx = int(w["ctx"])


def activations(w, F):
    net = NumpyNet(w)
    X = KN.stack(F.astype(np.float32), net.ctx)
    return net(X)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="full")
    ap.add_argument("--lag", type=int, default=3)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--kick-only", action="store_true")
    ap.add_argument("--h1", type=int, default=128)
    ap.add_argument("--ctx", type=int, default=KN.CTX)
    args = ap.parse_args()
    T0 = time.time()
    nums = tracks(args.src)
    data = {n: load(n, args.src) for n in nums}
    data[HUMAN] = load(HUMAN, "full")   # the human check always runs on the whole Adrenaline track
    print(f"{len(data)} tracks loaded in {time.time() - T0:.0f}s", flush=True)
    train_nums = [n for n in nums if n != HUMAN]
    rng = np.random.default_rng(1)
    order = list(rng.permutation(train_nums))
    folds = [order[i::args.folds] for i in range(args.folds)]
    acts = {}
    for fi, test in enumerate(folds):
        tr = [data[n] for n in train_nums if n not in test]
        w = train(tr, args.lag, args.epochs, h1=args.h1, ctx=args.ctx, kick_only=args.kick_only)
        for n in test:
            acts[n] = activations(w, data[n][0])
        print(f"fold {fi} done ({time.time() - T0:.0f}s)", flush=True)
    # final model: all tracks except Adrenaline
    wf = train([data[n] for n in train_nums], args.lag, args.epochs, h1=args.h1, ctx=args.ctx, log=True, kick_only=args.kick_only)
    acts[HUMAN] = activations(wf, data[HUMAN][0])
    lag = args.lag
    tag = f"{args.src}_lag{lag}" + (f"_{args.tag}" if args.tag else "")
    np.savez(os.path.join(HERE, f"kn_acts_{tag}.npz"), **{n: v for n, v in acts.items()})
    np.savez(os.path.join(HERE, f"kn_w_{tag}.npz"), **wf)
    print(f"saved bench/kn_acts_{tag}.npz  (score: bench/kn_score.py bench/kn_acts_{tag}.npz --src {args.src} --lag {lag})")
    if args.export:
        np.savez(os.path.join(ROOT, "listener", "kicknet.npz"), **wf)
        print("exported listener/kicknet.npz")
    print(f"total {time.time() - T0:.0f}s")


if __name__ == "__main__":
    main()
