"""Write drums_check.flac next to a track's full drum stem: the stem with a tick on every onset the bench
labels as a kick (high tick, left+right) or snare (low tick), so the labels can be checked by ear.
  listener/.venv/Scripts/python.exe bench/label_check.py 14,44,08,12
"""
import os, sys
import numpy as np, soundfile as sf
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import bench as B
FULL = os.path.join(B.MUSIC, "analysis", "full")
for num in sys.argv[1].split(","):
    p = os.path.join(FULL, num, "drums.flac")
    x, sr = B.read_mono(p)
    _, k, s = B.drum_hits(x, sr)
    y = x / (np.abs(x).max() + 1e-9) * 0.7
    def tick(freq, dur=0.025):
        t = np.arange(int(dur * sr)) / sr
        return np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.006) * 0.5
    for times, f in ((k, 3000.0), (s, 900.0)):
        tk = tick(f)
        for t in times:
            i = int(t * sr)
            j = min(len(y), i + len(tk))
            if 0 <= i < len(y):
                y[i:j] += tk[:j - i]
    sf.write(os.path.join(FULL, num, "drums_check.flac"), np.clip(y, -1, 1), sr)
    print(num, len(k), "kicks", len(s), "snares")
