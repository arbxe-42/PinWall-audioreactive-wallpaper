"""The current live trigger (detect.py kick_fast) scored exactly like KickNet (bench/kn_score.py), on the
same tracks and labels (kn_cache must exist: run kn_train.py first). Parallel over tracks.

  listener/.venv/Scripts/python.exe bench/kn_baseline.py [--src drop|full] [--tag name] [k=v detector params]
"""
import json
import os
import sys
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "listener"))
import bench as B  # noqa: E402
import kn_train as K  # noqa: E402
import kn_score as S  # noqa: E402


def run(job):
    num, src, params = job
    from detect import Detector
    F, k, s, t0, a, b = K.load(num, src)
    drops = json.load(open(B.DROPS, encoding="utf-8"))
    meta = drops.get(num)
    import glob
    mixp = B.find_mix(num, meta["file"]) if meta else sorted(glob.glob(os.path.join(B.MUSIC, f"{num} - *.wav")))[0]
    x, sr = B.read_mono(mixp, t0, None if src == "full" else b)
    d = Detector(sr, params=params)
    hits, emit = [], []
    for i in range(0, len(x), 480):
        for e in d.process(x[i:i + 480]):
            if e["type"] == "kick_fast":
                hits.append(e["t"] + t0); emit.append(e["emit"] + t0)
    return num, np.array(hits), np.array(emit)


def main():
    args = [a for a in sys.argv[1:] if "=" not in a]
    src = args[args.index("--src") + 1] if "--src" in args else "drop"
    tag = args[args.index("--tag") + 1] if "--tag" in args else "baseline"
    params = {kv.split("=")[0]: float(kv.split("=")[1]) for kv in sys.argv[1:] if "=" in kv}
    nums = [n for n in K.tracks(src) if n != K.HUMAN]
    jobs = [(n, src, params) for n in nums] + [(K.HUMAN, "full", params)]
    with Pool(int(os.environ.get("KN_PROCS", "6"))) as pool:
        res = pool.map(run, jobs)
    hits = {}
    for num, h, e in res[:-1]:
        hits[num] = (h, e)
    np.savez(os.path.join(HERE, f"kn_hits_{tag}_{src}.npz"), **{n: np.stack([h, e]) for n, (h, e) in hits.items()},
             human=res[-1][1])
    for n in nums:
        K.load(n, src)
    m = S.machine(hits, nums, src)
    h = K.human_score(res[-1][1])
    print(S.fmt(tag, m, h))


if __name__ == "__main__":
    main()
