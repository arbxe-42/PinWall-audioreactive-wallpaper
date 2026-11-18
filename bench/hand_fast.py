"""kick_fast settings scored against the user's Adrenaline marks (63-127 s, kick + snare lanes, ±100 ms,
best constant shift), plus the vocal-track numbers from the stems. Args: k=v detector params."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'listener'))
import bench as B
from detect import Detector
P = {kv.split('=')[0]: float(kv.split('=')[1]) for kv in sys.argv[1:]}
drops = json.load(open(B.DROPS, encoding='utf-8'))
x, sr = B.read_mono(B.find_mix('14', drops['14']['file']), 10, 128)
d = Detector(sr, params=P); hits = []
for i in range(0, len(x), 480):
    for e in d.process(x[i:i + 480]):
        if e['type'] == 'kick_fast':
            t = e['t'] + 10
            if 63 <= t <= 127: hits.append(t)
hits = np.array(hits)
hk, hs = B.adrenaline_hand_lanes()
marks = np.array(sorted(t for t in hk + hs if 63 <= t <= 127))
best = None
for sh in np.arange(0.2, 0.6, 0.005):
    m = marks - sh
    p = np.mean([np.min(np.abs(m - h)) <= 0.1 for h in hits]); r = np.mean([np.min(np.abs(hits - x_)) <= 0.1 for x_ in m])
    f = 2 * p * r / (p + r + 1e-9)
    if best is None or f > best[0]: best = (f, sh, p, r)
print(P, f"hits {len(hits)}  on your marks {best[2]:.0%}  your marks caught {best[3]:.0%}")
