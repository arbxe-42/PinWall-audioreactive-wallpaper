"""Pin Wall label checker: a local page to listen to each track (mix or drum stem), see the stem-derived
kick / snare labels and the detectors' hits, and annotate them. Local only (127.0.0.1); the audio is the
user's own and never leaves this machine.

  listener/.venv/Scripts/python.exe tools/annotate/server.py   ->  http://127.0.0.1:4353

Annotations: bench/annotations/<NN>.json  {kick_add, snare_add, wrong, misfire, offset_ms, notes, updated}
"""
import glob
import http.server
import json
import os
import sys
import time
import urllib.parse

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
BENCH = os.path.join(ROOT, "bench")
sys.path.insert(0, BENCH)
sys.path.insert(0, os.path.join(ROOT, "listener"))
import bench as B  # noqa: E402
import stem_labels as SL  # noqa: E402

LABELS = 7   # stem labeller version: cache entries from an older one are rebuilt

FULL = os.path.join(B.MUSIC, "analysis", "full")
ANN = os.path.join(BENCH, "annotations")
CACHE = os.path.join(HERE, "cache")
PORT = 4353
os.makedirs(ANN, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)


def tracks():
    out = []
    for f in sorted(glob.glob(os.path.join(B.MUSIC, "*.wav"))):
        num = os.path.basename(f)[:2]
        if os.path.exists(os.path.join(FULL, num, "drums.flac")):
            name = os.path.splitext(os.path.basename(f))[0][5:]
            a = os.path.join(ANN, f"{num}.json")
            out.append({"num": num, "name": name, "annotated": os.path.exists(a)})
    return out


def device():
    """The output device and delay the listener is using right now (last 'capturing' line of its log)."""
    log = os.path.join(ROOT, "listener", "listener.log")
    name, delay = "?", 0.0
    try:
        with open(log, encoding="utf-8") as f:
            for line in f.readlines()[-4000:]:
                if " capturing " in line and " delay " in line:
                    a = line.split(" capturing ", 1)[1].rsplit(" delay ", 1)
                    name, delay = a[0].strip(), float(a[1])
    except OSError:
        pass
    return {"name": name, "delay_ms": round(delay * 1000)}


def mix_path(num):
    return sorted(glob.glob(os.path.join(B.MUSIC, f"{num} - *.wav")))[0]


def env(x, sr, rate=200):
    """Peak envelope at exactly `rate` bins per second (bin edges rounded per bin: sr // rate samples per bin
    drifted 0.23% at 44.1 kHz and drew the waveform ~0.4 s late by 3 minutes)."""
    n = int(len(x) / sr * rate)
    edges = np.round(np.arange(n) * sr / rate).astype(np.int64)
    e = np.maximum.reduceat(np.abs(x), edges)[:n]
    e = e / (np.percentile(e, 99.5) + 1e-9)
    return [int(v) for v in np.clip(e * 100, 0, 100)]


def live_pick(A, lag=3):
    """The live trigger's picking rule (detect.py _nn_frame), on precomputed activations."""
    import detect
    defaults = dict(nn_kick=0.5, nn_snare=0.5, nn_gap=0.09, nn_idle=1.5, nn_idle_thr=0.8)
    src = open(detect.__file__, encoding="utf-8").read()
    import re
    for k in defaults:
        m = re.search(rf"{k}=([0-9.]+)", src)
        if m:
            defaults[k] = float(m.group(1))
    out, last = [], -10 ** 9
    for n in range(1, len(A)):
        if n - last < defaults["nn_gap"] * 100:
            continue
        idle = n - last > defaults["nn_idle"] * 100
        tk = max(defaults["nn_kick"], defaults["nn_idle_thr"]) if idle else defaults["nn_kick"]
        ts = max(defaults["nn_snare"], defaults["nn_idle_thr"]) if idle else defaults["nn_snare"]
        if (A[n, 0] >= tk and A[n, 0] >= A[n - 1, 0]) or (A[n, 1] >= ts and A[n, 1] >= A[n - 1, 1]):
            out.append(n); last = n
    return (np.array(out) - lag + 1) / 100.0


def detector_hits(num):
    """Hits of the live trigger (kick_fast) and of KickNet on this track, if the bench has produced them."""
    out = {}
    p = os.path.join(BENCH, "kn_hits_baseline_full.npz")
    if os.path.exists(p):
        z = np.load(p)
        key = "human" if num == "14" else num
        if key in z:
            arr = z[key]
            out["live"] = [round(float(t), 3) for t in (arr if arr.ndim == 1 else arr[0])]
    # the live KickNet (v7, kick-only): held-out activations (each track scored by a fold model that never saw it;
    # Adrenaline by the final model), with the live thresholds
    p = os.path.join(BENCH, "kn_acts_full_lag3_v7k.npz")
    if os.path.exists(p):
        z = np.load(p)
        if num in z:
            sys.path.insert(0, os.path.join(ROOT, "listener"))
            tt = live_pick(z[num])
            out["kicknet"] = [round(float(t), 3) for t in tt]
    return out


def data(num):
    cp = os.path.join(CACHE, f"{num}.json")
    d = json.load(open(cp, encoding="utf-8")) if os.path.exists(cp) else None
    if not d or d.get("lv") != LABELS:
        st, sr = B.read_mono(os.path.join(FULL, num, "drums.flac"))
        lab = SL.label(st, sr)
        r = lambda a: [round(float(t), 3) for t in a]
        if d and "env_mix" in d and d.get("lv", 0) >= 5:
            em = d["env_mix"]; dur = d["dur"]
        else:
            x, sr2 = B.read_mono(mix_path(num)); em = env(x, sr2); dur = len(x) / sr2
        d = {"num": num, "dur": dur, "kicks": r(lab["kicks"]), "snares": r(lab["snares"]), "hats": r(lab["hats"]),
             "onsets": r(lab["onsets"]), "env_mix": em, "env_drums": env(st, sr), "env_rate": 200, "lv": LABELS}
        json.dump(d, open(cp, "w", encoding="utf-8"))
    d["hits"] = detector_hits(num)
    a = os.path.join(ANN, f"{num}.json")
    d["ann"] = json.load(open(a, encoding="utf-8")) if os.path.exists(a) else None
    return d


class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _file(self, path, ctype):
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        a, b = 0, size - 1
        if rng and rng.startswith("bytes="):
            s, _, e = rng[6:].partition("-")
            a = int(s) if s else 0
            b = int(e) if e else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(b - a + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(a)
            left = b - a + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                    return
                left -= len(chunk)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        if not parts:
            return self._file(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
        if parts == ["tracks"]:
            return self._json(tracks())
        if parts == ["device"]:
            return self._json(device())
        if len(parts) == 2 and parts[0] == "data":
            return self._json(data(parts[1][:2]))
        if len(parts) == 3 and parts[0] == "audio":
            num = parts[2][:2]
            if parts[1] == "mix":
                return self._file(mix_path(num), "audio/wav")
            if parts[1] == "drums":
                return self._file(os.path.join(FULL, num, "drums.flac"), "audio/flac")
        self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        if len(parts) == 2 and parts[0] == "save":
            num = parts[1][:2]
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if body.get("lv") != LABELS:   # a tab opened before the labels changed: its times may be stale
                return self._json({"ok": False, "error": "This page is out of date: reload it (F5). Your last change was not saved."}, 409)
            body["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            json.dump(body, open(os.path.join(ANN, f"{num}.json"), "w", encoding="utf-8"), indent=1)
            return self._json({"ok": True, "updated": body["updated"]})
        self.send_error(404)


if __name__ == "__main__":
    print(f"label checker on http://127.0.0.1:{PORT}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
