"""End-to-end beat timing test across output delays and a mid-song device switch.

For each scenario: a silent replay of a track's 48 s drop window runs through the real listener on its own
port (speaker delay simulated), the wallpaper's own beat code (audio.js, in Node) fires beats, and every
fired beat is compared with the drum stem's real hits *as you would hear them* (replay start + song time
+ output buffering + the simulated speaker delay).

Run: listener/.venv/Scripts/python.exe tools/e2e_run.py
"""
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, os.path.join(ROOT, "listener"))
import bench as B  # noqa: E402

PY = os.path.join(ROOT, "listener", ".venv", "Scripts", "python.exe")
OUT = os.path.join(ROOT, "test", "e2e")
os.makedirs(OUT, exist_ok=True)

TRACKS = (sys.argv[1].split(",") if len(sys.argv) > 1 else ["08", "21", "40", "14", "13"])
SCENARIOS = [("laptop", 0.0, None, None), ("k3", 0.25, None, None), ("k3->laptop", 0.25, 22.0, 0.0)]


def run_batch(jobs):
    procs = []
    for j in jobs:
        meta = j["meta"]
        args = [PY, os.path.join(ROOT, "listener", "server.py"), "--replay", B.find_mix(j["num"], meta["file"]),
                "--start", str(meta["window"][0]), "--duration", "48", "--port", str(j["port"]),
                "--delay", str(j["delay"]), "--info", j["info"]]
        if j["switch"] is not None:
            args += ["--switch-at", str(j["switch"]), "--delay2", str(j["delay2"])]
        procs.append(subprocess.Popen(args, cwd=os.path.join(ROOT, "listener"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(0.6)
    nodes = [subprocess.Popen(["node", os.path.join(ROOT, "tools", "e2e_beats.mjs"), str(j["port"]), j["out"], "52"], cwd=ROOT)
             for j in jobs]
    for n in nodes:
        n.wait()
    for p in procs:
        p.kill()


def score(j):
    info = json.load(open(j["info"]))
    res = json.load(open(j["out"]))
    meta = j["meta"]
    w0 = meta["window"][0]
    drums, sr = B.read_mono(os.path.join(B.MUSIC, "analysis", "drop", j["num"], "stems", "drums.flac"))
    hits, kicks, _ = B.drum_hits(drums, sr)   # song seconds from the window start
    def heard(s):
        d = info["delay"] if info["switch_at"] is None or s < info["switch_at"] else info["delay2"]
        return info["t0"] + s + info["base_out"] + d
    H = np.array([heard(s) for s in hits]) * 1000
    fired = np.array([f["t"] for f in res["fired"]], float)
    rows = []
    for t in fired:
        k = np.argmin(np.abs(H - t))
        rows.append(t - H[k])
    rows = np.array(rows)
    seg = lambda a, b: rows[(fired >= (info["t0"] + a) * 1000) & (fired < (info["t0"] + b) * 1000)] if len(rows) else np.array([])
    def stat(r):
        if not len(r):
            return dict(n=0, on=None, med=None)
        return dict(n=int(len(r)), on=round(float(np.mean(np.abs(r) <= 50)), 2), med=round(float(np.median(r[np.abs(r) <= 80])), 1) if np.any(np.abs(r) <= 80) else None)
    gaps = np.diff(np.concatenate([[info["t0"] * 1000], fired, [(info["t0"] + 48) * 1000]])) / 1000 if True else []
    sw = info["switch_at"]
    # the hits (what moves the pictures): on a kick? on any drum? phantoms per minute?
    K = np.array([heard(s) for s in kicks]) * 1000
    ht = np.array([h["t"] for h in res.get("hits", [])], float)
    def near(arr, ref, tol=50):
        return np.array([np.min(np.abs(ref - t)) <= tol for t in arr]) if len(arr) and len(ref) else np.zeros(len(arr), bool)
    on_kick, on_drum = near(ht, K), near(ht, H)
    hit_stats = dict(n=int(len(ht)), on_kick=round(float(on_kick.mean()), 2) if len(ht) else None,
                     on_drum=round(float(on_drum.mean()), 2) if len(ht) else None,
                     phantom_per_min=round(float((~on_drum).sum()) / 0.8, 1),
                     kicks_caught=round(float(near(K, ht, 50).mean()), 2) if len(K) else None)
    return dict(track=j["num"], scen=j["scen"], hits=hit_stats, all=stat(rows),
                before=stat(seg(0, sw)) if sw else None, after=stat(seg(sw, 48)) if sw else None,
                longest_gap_s=round(float(gaps.max()), 1))


def main():
    drops = json.load(open(B.DROPS, encoding="utf-8"))
    jobs = []
    port = 4371
    for num in TRACKS:
        for scen, d, sw, d2 in SCENARIOS:
            jobs.append(dict(num=num, meta=drops[num], scen=scen, delay=d, switch=sw, delay2=d2, port=port,
                             info=os.path.join(OUT, f"{num}_{scen.replace('>', '')}_info.json"),
                             out=os.path.join(OUT, f"{num}_{scen.replace('>', '')}_beats.json")))
            port += 1
    for i in range(0, len(jobs), 5):
        print("batch", i // 5 + 1, "of", (len(jobs) + 4) // 5, flush=True)
        run_batch(jobs[i:i + 5])
    results = [score(j) for j in jobs]
    for r in results:
        print(json.dumps(r))
    json.dump(results, open(os.path.join(OUT, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
