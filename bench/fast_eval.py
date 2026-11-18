"""Fast kick trigger vs the confirmed one: accuracy (stems + the user's marks) and latency (emit - real kick)."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'listener'))
import bench as B
from detect import Detector
params = {}
for kv in [a for a in sys.argv[1:] if '=' in a]:
    k, v = kv.split('='); params[k] = float(v)
drops = json.load(open(B.DROPS, encoding='utf-8'))
tot = {'td': [0, 0, 0, []], 'fast': [0, 0, 0, []], 'conf': [0, 0, 0, []]}
TR = (sys.argv[1].split(',') if len(sys.argv) > 1 and '=' not in sys.argv[1] else ['08', '21', '40', '14', '13', '01', '07', '30', '47', '23', '27', '44', '19', '15', '50', '12'])
for num in TR:
    m = drops[num]; w0, w1 = m['window']
    st, sr = B.read_mono(os.path.join(B.MUSIC, 'analysis', 'drop', num, 'stems', 'drums.flac'))
    allh, kicks, _ = B.drum_hits(st, sr); allh = allh + w0; kicks = kicks + w0
    x, sr2 = B.read_mono(B.find_mix(num, m['file']), w0 - 20, w1)
    d = Detector(sr2, params=params); ev = []
    for i in range(0, len(x), 480):
        for e in d.process(x[i:i + 480]):
            e = dict(e); e['t'] += w0 - 20
            if 'emit' in e: e['emit'] += w0 - 20
            ev.append(e)
    fast = [e for e in ev if e['type'] == 'kick_fast' and w0 <= e['t'] <= w1]
    td = [e for e in ev if e['type'] == 'kick_td' and w0 <= e['t'] <= w1]
    conf = [e for e in ev if e['type'] == 'kick_raw' and e.get('ok') and w0 <= e['t'] <= w1]
    for name, es in (('td', td), ('fast', fast), ('conf', conf)):
        ts = np.array([e['t'] for e in es])
        on_k = sum(np.min(np.abs(kicks - t)) <= 0.05 for t in ts) if len(kicks) else 0
        on_d = sum(np.min(np.abs(allh - t)) <= 0.05 for t in ts)
        tot[name][0] += len(ts); tot[name][1] += on_k; tot[name][2] += on_d
        for e in es:
            j = np.argmin(np.abs(kicks - e['t']))
            if abs(kicks[j] - e['t']) <= 0.05:
                emit = e.get('emit', e['t'] + 0.05)
                tot[name][3].append(((emit - kicks[j]) * 1000, (e['t'] - kicks[j]) * 1000))
    print(num, 'td', len(td), 'fast', len(fast), 'conf', len(conf), 'truth kicks', len(kicks))
for name, (n, k, dd, lat) in tot.items():
    if not n or not lat:
        continue
    lat = np.array(lat)
    print(f"{name}: {n} hits, on a real kick {k / max(1, n):.0%}, on any drum {dd / max(1, n):.0%}, "
          f"sent {np.median(lat[:, 0]):.0f} ms after the kick (p75 {np.percentile(lat[:, 0], 75):.0f}), stamp error {np.median(lat[:, 1]):+.0f} ms")
