"""Streaming beat, kick, snare and drop detector for Pin Wall.

Audio goes in as arbitrary-sized mono float blocks; events come out with times in seconds
(time of the sound, not time of detection). The same class runs live on loopback audio and
offline on files, so the offline bench measures exactly what the wallpaper will get.

Design (see live-wallpaper/README.md):
  * 10 ms hop STFT, log-compressed "SuperFlux" onset strength per band:
      kick  = flux 35-130 Hz
      snare = sqrt(flux 150-400 Hz * flux 1.5-8 kHz)   (needs body AND snap, so hats don't count)
      full  = flux over the whole spectrum            (for the beat clock)
  * adaptive peak picking (median + k * MAD over the last second, 20 ms lookahead)
  * a beat clock: tempo by autocorrelation of the last 6 s, phase by comb search, then a
    phase-locked loop that predicts every next beat and nudges itself toward real onsets
  * gating: once locked, kicks and snares are only reported on the beat grid (on-beat, or the
    off-beat 8th when strong). Unlocked = loose mode: no hard hits at all.
  * drop: big jump in loudness and bass after a lull, with a cooldown.
"""
from collections import deque
import math

import numpy as np

FPS = 100.0  # analysis frames per second (10 ms hop)


class Peaks:
    """Causal adaptive peak picker with a small lookahead."""

    def __init__(self, k, floor_frac, refractory, look=2, hist=100, maxhist=300):
        self.k, self.floor_frac, self.refr, self.look = k, floor_frac, refractory, look
        self.vals = deque(maxlen=hist)       # last second of values for median / MAD
        self.maxv = deque(maxlen=maxhist)    # last 3 s for the relative floor
        self.win = deque(maxlen=2 * look + 4)
        self.last = -1e9

    def push(self, n, v):
        """Feed frame n's value. Returns (frame, strength_z) for a peak confirmed `look` frames ago."""
        self.vals.append(v)
        self.maxv.append(v)
        self.win.append((n, v))
        if len(self.win) < self.look + 4:
            return None
        cn, cv = self.win[-1 - self.look]
        if cv <= 0:
            return None
        if cv < max(x for _, x in self.win):
            return None
        arr = np.fromiter(self.vals, float)
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med))) + 1e-9
        z = (cv - med) / mad
        floor = self.floor_frac * max(self.maxv)
        if z < self.k or cv < floor or cn - self.last < self.refr:
            return None
        self.last = cn
        return cn, z


class Detector:
    def __init__(self, sr, nfft=2048, params=None):
        p = dict(
            kick_k=4.0, kick_floor=0.18, snare_k=4.0, snare_floor=0.22, full_k=3.0, full_floor=0.12,
            tol=0.06,            # beat-grid tolerance, seconds
            fire=0.55,            # groove-memory probability needed to fire a hit in a slot
            rise_db=1.0, snap_ratio=10.0,  # kick candidate checks (see _frame)
            fast_k=5.0, fast_rise=3.0, fast_gap=0.11, fast_hold=0.18, sub_margin=-99.0, sub_big=8.0, gate_db=30.0,   # fast kick trigger
            td_lo_db=6.0, td_hi_db=4.0, td_lo_big=12.0, td_floor_db=14.0,   # time-domain kick trigger
            nn=1.0, nn_kick=0.5, nn_snare=2.0, nn_gap=0.09, nn_idle=1.5, nn_idle_thr=0.0, nn_peak=2,   # KickNet trigger (listener/kicknet.py, kicknet.npz); nn=0 = the older rules below
            learn_hit=0.4, learn_miss=0.4,
            lock_conf=0.6,       # fraction of recent beats backed by an onset
            bias=0.027,          # reported times minus this = the drum attack (bench-calibrated, 31 clips)
            drop_db=8.0, drop_bass_db=8.0, drop_cool=30.0, drop_lull=5.0,
            snare_fire=0.8,       # snares are hard to tell from claps/hats: only very regular ones fire
            bpm_lo=70.0, bpm_hi=200.0, bpm_centre=140.0, bpm_sigma=0.6,
        )
        if params:
            p.update(params)
        self.p = p
        self.sr = sr
        self.hop = int(round(sr / FPS))
        self.nfft = nfft
        self.win = np.hanning(nfft).astype(np.float32)
        self.wsum = float(self.win.sum())
        self.buf = np.zeros(nfft, np.float32)
        self.pending = np.zeros(0, np.float32)
        f = np.fft.rfftfreq(nfft, 1.0 / sr)
        self.m_kick = (f >= 35) & (f <= 130)
        self.m_sub = (f >= 35) & (f <= 90)
        self.m_lowmid = (f >= 160) & (f <= 500)
        self.m_mid = (f >= 500) & (f <= 2500)
        self.m_hi = (f >= 3000) & (f <= 11000)
        self.m_body = (f >= 150) & (f <= 400)
        self.m_snap = (f >= 1500) & (f <= 8000)
        self.m_full = (f >= 30) & (f <= 16000)
        self.m_bass = f < 150
        self.m_mid = (f >= 150) & (f < 2000)
        self.m_high = f >= 2000
        self.prev = None
        self.n = 0  # frame counter
        self.nn = None
        if p["nn"]:
            import kicknet
            try:
                self.nn = kicknet.Stream(sr, nfft, kicknet.Net())
            except OSError:
                self.nn = None   # no weights file: fall back to the rules
        self.nn_prev = (0.0, 0.0)
        self.nn_pending = None
        self.nn_last = -10 ** 9

        self.pk_kick = Peaks(p["kick_k"], p["kick_floor"], refractory=9)
        self.pk_snare = Peaks(p["snare_k"], p["snare_floor"], refractory=9)
        self.pk_full = Peaks(p["full_k"], p["full_floor"], refractory=7)

        # beat clock
        self.env = deque(maxlen=600)      # onset envelope, 6 s
        self.P = None                     # period in frames
        self.next_beat = None             # predicted frame of next beat
        self.beat_index = 0
        self.support = deque(maxlen=8)    # recent beats backed by an onset?
        self.disagree = 0
        self.recent_onsets = deque(maxlen=64)  # (frame, z) of full/kick peaks
        self.locked = False
        self.conf = 0.0

        # groove memory: probability of a kick / snare in each 8th-note slot of a 4-beat bar
        self.kick_cands = deque(maxlen=64)
        self.snare_cands = deque(maxlen=64)
        self.p_kick = np.zeros(8)
        self.p_snare = np.zeros(8)
        self.pending_off = None
        self.kick_on = 0.0
        self.kick_off = 0.0
        self.p_acc = np.zeros(4)
        self.slot_hist = deque(maxlen=8)   # kick heard in each of the last 8 eighth-note slots?
        self.active = False
        self.zref = 1.0
        self.kick_wait = deque()
        self.kick_vals = deque(maxlen=100)   # last second of kick flux, for the fast trigger
        self.band_hist = {b: deque(maxlen=100) for b in ('sub', 'lowmid', 'mid', 'hi')}
        self.band_db = {b: deque(maxlen=8) for b in ('sub', 'lowmid', 'mid', 'hi')}
        self.last_fast_jump = 0.0
        self.low_long = deque(maxlen=800)    # 8 s of kick-band level, for the loudness gate
        self.full_vals = deque(maxlen=12)
        self.last_fast = -1e9
        from scipy.signal import butter
        self._sos_lo = butter(2, 140, 'low', fs=sr, output='sos')
        self._sos_hi = butter(2, 2500, 'high', fs=sr, output='sos')
        self._zi_lo = np.zeros((self._sos_lo.shape[0], 2))
        self._zi_hi = np.zeros((self._sos_hi.shape[0], 2))
        self._env_lo = 0.0
        self._env_hi = 0.0
        self._lo_hist = deque(maxlen=200)   # 2 s of 10 ms low-envelope levels (dB)
        self._hi_hist = deque(maxlen=200)
        self._td_last = -1e9
        self._samples = 0
        self.kick_ok = deque(maxlen=64)
        self.hist_lowdb = deque(maxlen=16)
        self.hist_snap = deque(maxlen=16)
        self.snap_med = deque(maxlen=100)

        # loudness
        self.full_db = deque(maxlen=3000)  # 30 s
        self.bass_db = deque(maxlen=3000)
        self.fast_full = -120.0
        self.fast_bass = -120.0
        self.last_drop = -1e9
        self.silent_frames = 0
        self.levels = (0.0, 0.0, 0.0)
        self._lvmax = np.full(3, 1e-6)

    # ------------------------------------------------------------------ public
    def process(self, block):
        """Feed mono float32 samples. Returns a list of event dicts."""
        out = []
        x = np.concatenate([self.pending, np.asarray(block, np.float32)])
        i = 0
        while len(x) - i >= self.hop:
            self.buf = np.roll(self.buf, -self.hop)
            hopx = x[i:i + self.hop]
            self.buf[-self.hop:] = hopx
            i += self.hop
            if self.p.get("td_on"):
                out.extend(self._td_kick(hopx))   # experimental waveform trigger (off: slower CPU, less accurate)
            out.extend(self._frame())
        self.pending = x[i:]
        return out

    def _td_kick(self, h):
        """Time-domain kick trigger: the low end's envelope (filtered waveform, 5 ms smoothing) jumps,
        with a click (high band jumping) at the same moment. Reacts ~10 ms after the kick."""
        from scipy.signal import sosfilt
        lo, self._zi_lo = sosfilt(self._sos_lo, h, zi=self._zi_lo)
        hi, self._zi_hi = sosfilt(self._sos_hi, h, zi=self._zi_hi)
        a = 1.0 - math.exp(-1.0 / (0.005 * self.sr))
        e_lo = np.empty(len(h)); e_hi = np.empty(len(h))
        el, eh = self._env_lo, self._env_hi
        lo2, hi2 = lo * lo, hi * hi
        for k in range(len(h)):
            el += a * (lo2[k] - el); eh += a * (hi2[k] - eh)
            e_lo[k] = el; e_hi[k] = eh
        self._env_lo, self._env_hi = el, eh
        start = self._samples
        self._samples += len(h)
        db_lo = 10 * math.log10(el + 1e-12)
        db_hi = 10 * math.log10(eh + 1e-12)
        prev_lo = self._lo_hist[-2] if len(self._lo_hist) >= 2 else db_lo
        prev_hi = self._hi_hist[-2] if len(self._hi_hist) >= 2 else db_hi
        self._lo_hist.append(db_lo); self._hi_hist.append(db_hi)
        if len(self._lo_hist) < 100:
            return []
        loud = float(np.percentile(np.fromiter(self._lo_hist, float), 90))
        jump_lo, jump_hi = db_lo - prev_lo, db_hi - prev_hi
        tnow = self._samples / self.sr
        if (jump_lo >= self.p["td_lo_db"] and db_lo >= loud - self.p["td_floor_db"]
                and (jump_hi >= self.p["td_hi_db"] or jump_lo >= self.p["td_lo_big"])
                and tnow - self._td_last >= self.p["fast_gap"]):
            # onset time: where the low envelope first crossed halfway up its jump inside this hop
            target = 10 ** ((prev_lo + 3.0) / 10)
            k = int(np.argmax(e_lo >= target)) if np.any(e_lo >= target) else len(h) - 1
            self._td_last = tnow
            t_on = (start + k) / self.sr - 0.004
            return [{"type": "kick_td", "t": t_on, "emit": tnow, "jl": round(jump_lo, 1), "jh": round(jump_hi, 1)}]
        return []

    def _nn_frame(self, n, spec):
        """KickNet trigger: fire when the kick (or, at a higher bar, snare) activation crosses its threshold
        while rising. The network answers for the attack `lag` frames ago, so the hit is stamped there.
        The hit is sent nn_peak frames later with the PEAK confidence over those frames: at the crossing,
        real kicks and stray hits look alike (median 0.69 vs 0.61); 20 ms later real kicks have climbed
        (0.82) and strays stall (0.66), so the wallpaper can hit real kicks hard and strays softly. The
        timestamp stays on the attack (with Bluetooth delay the wait is invisible; on wired speakers +20 ms)."""
        k, sn = self.nn.push(spec)
        pk, ps = self.nn_prev
        self.nn_prev = (k, sn)
        out = []
        conf = k if self.p["nn_snare"] > 1 else max(k, sn)   # kick-only model (nn_snare > 1): kick head only
        if self.nn_pending is not None:
            hit = self.nn_pending
            hit["z"] = max(hit["z"], round(conf, 2))
            if n >= hit["_send"]:
                hit.pop("_send")
                hit["emit"] = (n + 1) * self.hop / self.sr
                out.append(hit)
                self.nn_pending = None
        if n - self.nn_last < self.p["nn_gap"] * FPS:
            return out
        # optional: after a quiet stretch (no hit for nn_idle s) the first hit must reach nn_idle_thr. OFF
        # (0.0) since 2026-11-18: with the kick-only model it blocked drop starts (first hit > 4 s late after
        # 13 of 75 pauses; drop kicks often sit at 0.6-0.75 confidence). Weak stray hits are soft anyway.
        idle = n - self.nn_last > self.p["nn_idle"] * FPS
        tk = max(self.p["nn_kick"], self.p["nn_idle_thr"]) if idle else self.p["nn_kick"]
        ts = max(self.p["nn_snare"], self.p["nn_idle_thr"]) if idle else self.p["nn_snare"]
        if (k >= tk and k >= pk) or (sn >= ts and sn >= ps):
            self.nn_last = n
            lag = self.nn.net.lag
            hit = {"type": "kick_fast", "t": (n - lag + 1) * self.hop / self.sr, "emit": (n + 1) * self.hop / self.sr,
                   "z": round(conf, 2), "z0": round(conf, 2), "nn": [round(k, 2), round(sn, 2)],
                   "_send": n + int(self.p["nn_peak"])}   # z becomes the peak; z0 stays the trigger value
            if self.p["nn_peak"] <= 0:
                hit.pop("_send"); out.append(hit)
            else:
                self.nn_pending = hit
        return out

    def t(self, frame):
        """Seconds of the sound for an analysis frame (frame end minus calibrated bias)."""
        return (frame + 1) * self.hop / self.sr - self.p["bias"]

    # ----------------------------------------------------------------- per frame
    def _frame(self):
        n = self.n
        self.n += 1
        ev = []
        spec = np.abs(np.fft.rfft(self.buf * self.win)) / self.wsum
        lm = np.log1p(spec * 1000.0)
        if self.prev is None:
            self.prev = lm
        ref = np.maximum(np.maximum(self.prev, np.roll(self.prev, 1)), np.roll(self.prev, -1))
        d = np.maximum(lm - ref, 0.0)
        self.prev = lm
        kick = float(d[self.m_kick].mean())
        snare = math.sqrt(float(d[self.m_body].mean()) * float(d[self.m_snap].mean()))
        full = float(d[self.m_full].mean())

        power = spec ** 2
        fdb = 10 * math.log10(float(power[self.m_full].sum()) + 1e-12)
        bdb = 10 * math.log10(float(power[self.m_bass].sum()) + 1e-12)
        self.fast_full += 0.15 * (fdb - self.fast_full)
        self.fast_bass += 0.15 * (bdb - self.fast_bass)
        self.full_db.append(fdb)
        self.bass_db.append(bdb)

        lv = np.array([power[self.m_bass].sum(), power[self.m_mid].sum(), power[self.m_high].sum()]) ** 0.5
        self._lvmax = np.maximum(self._lvmax * 0.9995, lv)
        self.levels = tuple(float(v) for v in lv / self._lvmax)

        # silence: forget the clock after 2 s of near silence
        if fdb < -70:
            self.silent_frames += 1
            if self.silent_frames == 200:
                self._reset_clock()
                ev.append({"type": "silence", "t": self.t(n)})
        else:
            self.silent_frames = 0

        self.env.append(0.6 * full + 0.4 * kick)

        self.hist_lowdb.append(10 * math.log10(float(power[self.m_kick].sum()) + 1e-12))
        snapv = float(d[self.m_snap].mean())
        self.hist_snap.append(snapv)
        self.snap_med.append(snapv)

        pf = self.pk_full.push(n, full)
        if pf:
            self.recent_onsets.append(pf)
        # FAST kick trigger: fire as soon as the low end starts jumping (no waiting for the peak), so hits
        # can reach the screen in time even on speakers with no delay. Time-stamped at the click (the
        # full-range attack within the last 40 ms), which is what the ear hears.
        self.kick_vals.append(kick)
        bands = {'sub': float(d[self.m_sub].mean()), 'lowmid': float(d[self.m_lowmid].mean()),
                 'mid': float(d[self.m_mid].mean()), 'hi': float(d[self.m_hi].mean())}
        bz = {}
        for b, v in bands.items():
            hst = self.band_hist[b]
            if len(hst) > 20:
                arr2 = np.fromiter(hst, float); md = float(np.median(arr2))
                bz[b] = (v - md) / (float(np.median(np.abs(arr2 - md))) + 1e-9)
            else:
                bz[b] = 0.0
            hst.append(v)
        self.bz = bz
        self.bands = bands
        for b, msk in (('sub', self.m_sub), ('lowmid', self.m_lowmid), ('mid', self.m_mid), ('hi', self.m_hi)):
            self.band_db[b].append(10 * math.log10(float(power[msk].sum()) + 1e-12))
        self.low_long.append(self.hist_lowdb[-1] if self.hist_lowdb else -120.0)
        self.full_vals.append((n, full))
        if self.nn is not None:
            ev.extend(self._nn_frame(n, spec))
        elif len(self.kick_vals) >= 50 and len(self.hist_lowdb) >= 6 and n - self.last_fast >= self.p["fast_gap"] * FPS:
            arr = np.fromiter(self.kick_vals, float)
            med = float(np.median(arr)); mad = float(np.median(np.abs(arr - med))) + 1e-9
            z = (kick - med) / mad
            rise = self.hist_lowdb[-1] - self.hist_lowdb[-4]
            bd = self.band_db
            r_sub = bd['sub'][-1] - bd['sub'][-4] if len(bd['sub']) >= 4 else 0.0
            r_lm = bd['lowmid'][-1] - bd['lowmid'][-4] if len(bd['lowmid']) >= 4 else 0.0
            # a kick's jump lives in the sub-bass; voices and snare bodies jump in 160-500 Hz
            sub_dom = r_sub >= r_lm + self.p["sub_margin"] or r_sub >= self.p["sub_big"]
            # just after a hit, the bass swelling back (sidechain) is not a new kick unless it jumps harder
            soon = n - self.last_fast < self.p["fast_hold"] * FPS
            # loudness gate: in a breakdown (voice, pads, no kick) the low end sits far below the drop;
            # the adaptive thresholds above would otherwise start firing on small low-end movements
            ref = float(np.percentile(np.fromiter(self.low_long, float), 90)) if len(self.low_long) > 100 else -120.0
            loud_enough = self.hist_lowdb[-1] >= ref - self.p["gate_db"]
            if (z >= self.p["fast_k"] and rise >= self.p["fast_rise"] and kick >= 0.25 * float(arr.max())
                    and sub_dom and loud_enough and (not soon or rise > self.last_fast_jump + 3.0)):
                self.last_fast_jump = rise
                self.last_fast = n
                fs = [f for f, v in self.full_vals if v >= 0.5 * max(v2 for _, v2 in self.full_vals)]
                att = min(fs) if fs else n
                att = max(att, n - 4)
                ev.append({"type": "kick_fast", "t": self.t(att), "emit": self.t(n) + self.p["bias"], "z": round(z, 1),
                           "rise": round(rise, 1), "r_sub": round(r_sub, 1), "r_lm": round(r_lm, 1),
                           "bz": {k: round(v, 1) for k, v in self.bz.items()},
                           "bf": {k: round(v, 4) for k, v in self.bands.items()}})
        pk = self.pk_kick.push(n, kick)
        if pk:
            self.kick_wait.append(pk)
        # A kick candidate is judged 3 frames after its peak: a real kick makes the low band
        # jump (>= rise_db over +-30 ms) without being mostly click (snare/clap/hat).
        while self.kick_wait and n >= self.kick_wait[0][0] + 3:
            cf, cz = self.kick_wait.popleft()
            back = n - cf
            lowdb = self.hist_lowdb
            if len(lowdb) > back + 3:
                rise = lowdb[-1 - back + 3] - lowdb[-1 - back - 3]
                s_peak = max(list(self.hist_snap)[-1 - back - 2:len(self.hist_snap) - back + 2] or [0.0])
                s_ratio = s_peak / (float(np.median(self.snap_med)) + 1e-9)
                # a kick makes the low end jump; lots of click alone means clap/snare, unless the low end
                # jumps hard too (kick and clap together on 2 and 4 in house/trance)
                ok = rise >= self.p["rise_db"] and (s_ratio < self.p["snap_ratio"] or rise >= 3.0)
                ev.append({"type": "kick_raw", "t": self.t(cf), "z": round(cz, 1), "ok": ok,
                           "rise": round(rise, 1), "snap": round(s_ratio, 1)})
                if ok:
                    self.kick_cands.append((cf, cz))
                    self.kick_ok.append((cf, cz))
        ps = self.pk_snare.push(n, snare)
        if ps:
            self.snare_cands.append(ps)
            ev.append({"type": "snare_raw", "t": self.t(ps[0]), "z": round(ps[1], 1)})

        if n % 25 == 0 and len(self.env) >= 400:
            self._tempo(n)
        tolF = self.p["tol"] * FPS
        if self.pending_off is not None and n >= self.pending_off[0] + tolF:
            ev.extend(self._slot(self.pending_off[0], self.pending_off[1]))
            self.pending_off = None
        if self.next_beat is not None and n >= self.next_beat + tolF:
            ev.extend(self._finish_beat())

        ev.extend(self._drop(n))
        return ev

    # ------------------------------------------------------------------ beat clock
    def _reset_clock(self):
        self.P = None
        self.next_beat = None
        self.support.clear()
        self.locked = False
        self.conf = 0.0
        self.disagree = 0
        self.p_kick[:] = 0
        self.p_snare[:] = 0
        self.pending_off = None

    def _tempo(self, n):
        e = np.fromiter(self.env, float)
        e = e - e.mean()
        if not np.any(e):
            return
        m = len(e)
        F = np.fft.rfft(e, 2 * m)
        ac = np.fft.irfft(F * np.conj(F))[:m]
        ac /= ac[0] + 1e-12
        lo = int(FPS * 60 / self.p["bpm_hi"])
        hi = int(FPS * 60 / self.p["bpm_lo"]) + 1
        lags = np.arange(lo, hi)
        score = ac[lags].copy()
        dbl = 2 * lags
        ok = dbl < m
        score[ok] += 0.5 * ac[dbl[ok]]
        bpm = 60 * FPS / lags
        prior = np.exp(-0.5 * (np.log2(bpm / self.p["bpm_centre"]) / self.p["bpm_sigma"]) ** 2)
        score *= prior
        j = int(np.argmax(score))
        L = float(lags[j])
        if 0 < j < len(lags) - 1:  # parabolic refinement
            a, b, c = score[j - 1], score[j], score[j + 1]
            den = a - 2 * b + c
            if den != 0:
                L += 0.5 * (a - c) / den
        self.peak_ac = float(ac[lags[j]])
        if self.P is None:
            self._seed(n, L)
            return
        if abs(L - self.P) / self.P > 0.04:
            # while locked, a "new" tempo that is just double, half or 2/3 of the current one is the
            # same music read at another level (drum'n'bass half time): keep the clock, don't reset
            ratio = L / self.P
            harmonic = any(abs(ratio - h) / h < 0.06 for h in (0.5, 2.0, 1.5, 2 / 3, 3.0, 1 / 3))
            if self.locked and harmonic:
                self.disagree = 0
                return
            self.disagree += 1
            if self.disagree >= (16 if self.locked else 8):
                self._seed(n, L)
        else:
            self.disagree = 0
            self.P += 0.1 * (L - self.P)

    def _seed(self, n, L):
        """Start the clock: period L, phase from a comb search over the recent envelope."""
        e = np.fromiter(self.env, float)
        m = len(e)
        best, best_phi = -1, 0
        for phi in range(int(L)):
            idx = (m - 1 - phi - np.arange(0, 12) * L).round().astype(int)
            idx = idx[idx >= 0]
            s = e[idx].sum()
            if s > best:
                best, best_phi = s, phi
        self.P = L
        self.next_beat = (n - best_phi) + L
        while self.next_beat < n:
            self.next_beat += L
        self.support.clear()
        self.locked = False
        self.disagree = 0
        self.p_kick[:] = 0
        self.p_snare[:] = 0
        self.pending_off = None

    def _finish_beat(self):
        """The predicted beat time has passed: score it, emit it, correct the clock."""
        tolF = self.p["tol"] * FPS
        pred = self.next_beat
        best = None
        # phase follows real kicks first (they are what the eye syncs to), else any strong onset
        for pool in (self.kick_ok, self.recent_onsets):
            for f, z in pool:
                if abs(f - pred) <= tolF and (best is None or z > best[1]):
                    best = (f, z)
            if best:
                break
        # a kick's low end peaks 20-40 ms after its click; the ear hears the click, so lock the clock
        # to the full-range attack just before the kick when there is one
        if best:
            att = [f for f, z in self.recent_onsets if best[0] - 5 <= f <= best[0] + 1]
            if att:
                best = (min(att), best[1])
        self.support.append(1.0 if best else 0.0)
        if len(self.support) >= 4:
            self.conf = float(np.mean(self.support))
        was = self.locked
        # hysteresis: lock at lock_conf, but once locked only let go when support really collapses
        if self.locked:
            self.locked = self.conf >= self.p["lock_conf"] - 0.25
        else:
            self.locked = len(self.support) >= 6 and self.conf >= self.p["lock_conf"]
        pos = self.beat_index % 4
        z = best[1] if best else 0.0
        self.zref = max(self.zref * 0.995, z) if z else self.zref * 0.995
        acc_now = min(1.0, z / (self.zref + 1e-9)) if z else 0.0
        accent = float(self.p_acc[pos])            # what a live system knows before the beat
        self.p_acc[pos] += 0.3 * (acc_now - self.p_acc[pos])
        down = int(np.argmax(self.p_kick[0::2] + 0.5 * self.p_acc))
        ev = [{"type": "beat", "t": self.t(pred), "locked": self.locked, "conf": round(self.conf, 2),
               "bpm": round(60 * FPS / self.P, 2), "i": self.beat_index, "pos": pos,
               "accent": round(accent, 2), "down": pos == down}]
        if self.locked != was:
            ev.append({"type": "lock" if self.locked else "loose", "t": self.t(pred)})
        slot = (self.beat_index % 4) * 2
        ev.extend(self._slot(pred, slot))
        self.pending_off = (pred + self.P / 2, slot + 1)
        self.beat_index += 1
        err = (best[0] - pred) if best else 0.0
        self.next_beat = pred + 0.3 * err + self.P
        self.P += 0.03 * err
        self.last_beat = pred
        # Kicks keep landing on the off-beat half: the clock is following hats. Slide it half a
        # beat so beats sit on the kicks (what the eye syncs to), and relearn the groove.
        if self.kick_off > 4 and self.kick_off > 2.5 * self.kick_on:
            self.next_beat += self.P / 2
            self.pending_off = None
            self.kick_on, self.kick_off = self.kick_off, 0.0
            self.p_kick = np.roll(self.p_kick, -1)
            self.p_snare = np.roll(self.p_snare, -1)
            ev.append({"type": "flip", "t": self.t(pred)})
        return ev

    def _slot(self, at, slot):
        """An 8th-note grid slot has passed. Decide the hit from the groove memory as it stood
        BEFORE this slot (that is all a live system knows in time), then learn from what was heard.
        Hits only ever land on predicted grid times, so off-beat phantoms cannot happen."""
        tolF = self.p["tol"] * FPS
        ev = []
        fire_k = self.locked and self.p_kick[slot] >= self.p["fire"]
        fire_s = self.locked and not fire_k and self.p_snare[slot] >= self.p["snare_fire"]
        if fire_k:
            ev.append({"type": "kick", "t": self.t(at), "p": round(float(self.p_kick[slot]), 2), "slot": slot})
        if fire_s:
            ev.append({"type": "snare", "t": self.t(at), "p": round(float(self.p_snare[slot]), 2), "slot": slot})
        # the clock sits on the attack; a kick's low-end peak (what kick_cands holds) comes up to ~50 ms later
        hk = any(-tolF <= f - at <= tolF + 5 for f, z in self.kick_cands)
        hs = any(abs(f - at) <= tolF for f, z in self.snare_cands) and not hk
        # kicks really present lately? (at least 2 of the last 8 eighth-note slots) - no kicks, no hits
        self.slot_hist.append(1 if hk else 0)
        self.active = sum(self.slot_hist) >= 2
        self.kick_on *= 0.97
        self.kick_off *= 0.97
        if hk:
            if slot % 2 == 0:
                self.kick_on += 1
            else:
                self.kick_off += 1
        for arr, obs in ((self.p_kick, hk), (self.p_snare, hs)):
            a = self.p["learn_hit"] if obs else self.p["learn_miss"]
            arr[slot] += a * ((1.0 if obs else 0.0) - arr[slot])
        return ev

    # ------------------------------------------------------------------ drops
    def _drop(self, n):
        if len(self.full_db) < 600 or (n - self.last_drop) < self.p["drop_cool"] * FPS:
            return []
        full = np.fromiter(self.full_db, float)
        bass = np.fromiter(self.bass_db, float)
        lull_f = float(np.median(full[-400:-50]))
        lull_b = float(np.median(bass[-400:-50]))
        top = float(np.percentile(full, 95))
        # a drop comes out of a quieter stretch of MUSIC: music starting after silence is not a drop
        if (self.fast_full - lull_f >= self.p["drop_db"] and self.fast_bass - lull_b >= self.p["drop_bass_db"]
                and lull_f <= top - self.p["drop_lull"] and float(np.min(full[-400:-50])) > -75.0):
            self.last_drop = n
            # the jump started a few frames ago; place it at the steepest recent rise
            rise = np.diff(full[-30:])
            k = int(np.argmax(rise))
            f0 = n - (30 - 1 - k)
            return [{"type": "drop", "t": self.t(f0), "jump_db": round(self.fast_full - lull_f, 1)}]
        return []
