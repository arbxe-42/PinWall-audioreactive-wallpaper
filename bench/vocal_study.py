"""What separates real kicks from vocal-triggered hits? Labels every kick_fast trigger from the stems."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'listener'))
import bench as B
from detect import Detector
PARAMS = {kv.split('=')[0]: float(kv.split('=')[1]) for kv in sys.argv[1:] if '=' in kv}
TR = sys.argv[1].split(',') if len(sys.argv) > 1 and '=' not in sys.argv[1] else ['27', '44', '19', '15', '41', '12', '50', '23', '08', '21', '40', '13', '30', '37', '14']
drops = json.load(open(B.DROPS, encoding='utf-8'))
rows = []
for num in TR:
    m = drops[num]; w0, w1 = m['window']
    base = os.path.join(B.MUSIC, 'analysis', 'drop', num, 'stems')
    dr, sr = B.read_mono(os.path.join(base, 'drums.flac'))
    allh, kicks, sn = B.drum_hits(dr, sr)
    vo, _ = B.read_mono(os.path.join(base, 'vocals.flac'))
    vd, vf, vt, _, hop = B._stem_flux(vo, sr)
    vfull = vd[:, (vf >= 100) & (vf <= 4000)].mean(1)
    vidx = B._pick(vfull, 0.25, int(0.06 / (hop / sr)))
    von = vt[vidx] if len(vidx) else np.array([])
    x, sr2 = B.read_mono(B.find_mix(num, m['file']), w0 - 20, w1)
    d = Detector(sr2, params=PARAMS)
    for i in range(0, len(x), 480):
        for e in d.process(x[i:i + 480]):
            if e['type'] != 'kick_fast':
                continue
            t = e['t'] + (w0 - 20) - w0
            if not 0 <= t <= w1 - w0:
                continue
            near = lambda arr: len(arr) and np.min(np.abs(arr - t)) <= 0.05
            lab = 'KICK' if near(kicks) else ('SNARE' if near(sn) else ('DRUM' if near(allh) else ('VOCAL' if near(von) else 'OTHER')))
            rows.append(dict(num=num, lab=lab, z=e['z'], rise=e['rise'], **{'z_' + k: v for k, v in e['bz'].items()},
                             **{'f_' + k: v for k, v in e['bf'].items()}))
    print(num, {L: sum(1 for r in rows if r['num'] == num and r['lab'] == L) for L in ('KICK', 'SNARE', 'DRUM', 'VOCAL', 'OTHER')}, flush=True)
json.dump(rows, open(os.path.join(HERE, 'vocal_study_' + ('_'.join(sys.argv[1:]) or 'default').replace('=', '') + '.json'), 'w'))
