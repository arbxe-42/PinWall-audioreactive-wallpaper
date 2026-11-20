// Music input: the Pin Wall listener (beat clock over WebSocket) with Lively's coarse audio feed as
// a fallback for smooth levels only. Beats fire from the listener's predicted clock, so a hit is
// always on the beat; when the clock isn't locked, no hits fire at all.
// Fire visuals this many ms early: the screen shows a frame ~1-2 frames after it is drawn.
export const LEAD = 45;
// Hit feel: 1 = the "settled" feel always (40-hit, peak; current choice, 04:25), 0 = the 30 s contrast curve always,
// null = crossfade (start-of-drop curve for the first 10 s of a section, then the settled feel). See _hit.
const PIN_SETTLE = 1;
// The settled feel scales the 20 ms peak confidence (true, since 2026-11-18 03:40) or the trigger confidence
// (false: the version the user picked at 03:25, fun but too close between real kicks and extras).
const SETTLED_USES_PEAK = true;

export class Music {
  constructor() {
    this.ws = null; this.connected = false;
    this.mode = 'reactive';
    this.clock = null;           // {next, period, locked, pos, accent, down}
    this.lastFired = 0;
    this.levels = { b: 0, m: 0, h: 0 };
    this.target = { b: 0, m: 0, h: 0 };
    this.lastLevelAt = 0;
    this.lastBeatAt = 0;
    this.handlers = { beat: [], hit: [], drop: [], mode: [], device: [] };
    this.zs = [];
    this.zsOld = [];   // confidences of the last 40 hits (the "settled" strength, see _hit)
    this.liveMax = [1e-3, 1e-3, 1e-3];
    this.device = '';
    // kick tape (the strip under the clock): per 10 ms frame [heard ms, loudness, KickNet confidence], and the
    // hits [heard ms, confidence]; the last 6 s, reactive mode only (the listener sends none in ambient)
    this.tapeA = []; this.tapeK = []; this.tapeHits = [];
    this._connect();
  }

  on(ev, fn) { this.handlers[ev].push(fn); }
  emit(ev, x) { for (const f of this.handlers[ev]) f(x); }

  _connect() {
    let ws;
    try { ws = new WebSocket('ws://127.0.0.1:' + (new URLSearchParams(location.search).get('ws') || 4360)); } catch (e) { setTimeout(() => this._connect(), 3000); return; }
    this.ws = ws;
    ws.onopen = () => { this.connected = true; };
    ws.onclose = () => { this.connected = false; this.clock = null; setTimeout(() => this._connect(), 3000); };
    ws.onerror = () => {};
    ws.onmessage = ev => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.type === 'clock') this._clock(m);
      else if (m.type === 'levels') { this.target = { b: m.b, m: m.m, h: m.h }; this.lastLevelAt = Date.now(); }
      else if (m.type === 'drop') this._drop(m);
      else if (m.type === 'hit') { this._tapeHit(m); this._hit(m); }
      else if (m.type === 'tape') this._tape(m);
      else if (m.type === 'reload') setTimeout(() => location.reload(), 300);   // new images were imported
      else if (m.type === 'mode') { this.mode = m.mode; this.emit('mode', m.mode); }
      else if (m.type === 'hello') { this.mode = m.mode; this.device = m.device; this.emit('mode', m.mode); this.emit('device', m); }
      else if (m.type === 'silence') { this.clock = null; this.zs = []; this.zsOld = []; }
    };
  }

  _tape(m) {
    for (let i = 0; i < m.a.length; i++) {
      this.tapeA.push([m.t + i * m.dt, m.a[i]]);
      this.tapeK.push([m.t + (i - m.lag) * m.dt, m.k[i]]);
    }
    const old = Date.now() - 6000;
    for (const arr of [this.tapeA, this.tapeK]) {
      let n = 0; while (n < arr.length && arr[n][0] < old) n++;
      if (n) arr.splice(0, n);
    }
  }

  _tapeHit(m) {
    this.tapeHits.push([m.at, m.z]);
    const old = Date.now() - 6000;
    while (this.tapeHits.length && this.tapeHits[0][0] < old) this.tapeHits.shift();
  }

  setMode(mode) {
    this.mode = mode;
    if (this.connected) this.ws.send(JSON.stringify({ type: 'mode', mode }));
    this.emit('mode', mode);
  }

  _clock(m) {
    // The listener announces a predicted beat. With speaker delay (Bluetooth: ~250 ms) the beat it
    // calls "next" can be one AFTER a beat that hasn't been heard yet, and a fresh message arrives
    // every beat, so the wallpaper must step back to the earliest beat still to come, or it would
    // keep chasing a target that moves away and never fire at all.
    const now = Date.now(), P = m.period;
    let next = m.next, shift = 0;
    while (next - P > now && next - P - this.lastFired > P * 0.5) { next -= P; shift--; }
    while (next - this.lastFired < P * 0.5) { next += P; shift++; }
    this.clock = { next, period: P, locked: m.locked, pos: (((m.pos + shift) % 4) + 4) % 4, accent: m.accent, down: m.down, bpm: m.bpm,
                   active: m.active !== false, pk: m.pk || null, half: this.clock && this.clock.half };
  }

  _drop(m) {
    this.sectionStart = m.at;   // a drop starts a new section: the wall uses the start-of-drop strength again
    const wait = Math.max(0, m.at - Date.now());
    setTimeout(() => this.emit('drop', m), wait);
  }

  // Lively's audio feed (128 bands, ~16 per second): smooth levels only.
  livelyAudio(arr) {
    if (this.connected && Date.now() - this.lastLevelAt < 1000) return;
    const avg = (a, b) => { let s = 0; for (let i = a; i < b; i++) s += arr[i]; return s / (b - a); };
    const v = [avg(0, 8), avg(8, 48), avg(48, 128)];
    for (let i = 0; i < 3; i++) this.liveMax[i] = Math.max(this.liveMax[i] * 0.999, v[i]);
    this.target = { b: v[0] / this.liveMax[0], m: v[1] / this.liveMax[1], h: v[2] / this.liveMax[2] };
    this.lastLevelAt = Date.now();
  }

  // call every frame
  update(dt) {
    const k = 1 - Math.exp(-dt * 14);
    for (const c of ['b', 'm', 'h']) this.levels[c] += (this.target[c] - this.levels[c]) * k;
    if (Date.now() - this.lastLevelAt > 1500) for (const c of ['b', 'm', 'h']) this.target[c] *= 0.9;
    const c = this.clock;
    if (!c) return;
    const now = Date.now() + LEAD;
    if (now - c.next > 2 * c.period) { c.next = now + c.period; c.half = null; return; }   // stale: resync quietly
    while (now >= c.next) {
      const pos = c.pos;
      this.lastFired = c.next;
      if (c.locked) {
        this.lastBeatAt = Date.now();
        this.emit('beat', { pos, accent: c.accent ? c.accent[pos] : 0.5, down: pos === c.down, bpm: c.bpm, period: c.period });
      }
      c.next += c.period;
      c.pos = (pos + 1) % 4;
    }
  }

  // A hit = a kick the listener actually heard (snares too: they carry a kick underneath in this music).
  // It is scheduled for the moment you hear it; on laptop speakers that moment has usually just passed,
  // so it fires at once (~40 ms late); on Bluetooth speakers there is time to land it exactly.
  _hit(m) {
    // recent hits: the last 30 s
    const now = Date.now();
    this.zs.push([now, m.z]);
    while (this.zs.length && now - this.zs[0][0] > 30000) this.zs.shift();
    const sorted = this.zs.map(v => v[1]).sort((a, b) => a - b);
    let strength, soft = false;
    if (m.z <= 1) {
      // KickNet: z is the confidence PEAK over the 20 ms after the trigger (real kicks ~0.82, strays ~0.66).
      // Full contrast, kick or no kick (the user: the old 200-hit version "would figure things out and have
      // full dynamics of 0 to 100" after ~30 s of a drop, but the first 20 s were weak). The full point `hi`
      // is the 70th percentile of the last 30 s of hits (0.7-0.9; 0.8 until 8 hits are in, so a drop is
      // strong from its first kick); 0.2 below it is ~0; a steep curve keeps strays near zero.
      // Over 30 songs: real kicks median 0.89, strays 0.16; first 8 s after a pause, real kicks 0.96.
      // (Before: 200-hit version 0.59 / 0.34 / 0.59; the 20 s guarded ramp 1.00 / 0.53 / 1.00.)
      let hi = sorted.length >= 8 ? sorted[Math.floor(sorted.length * 0.7)] : 0.8;
      hi = Math.min(0.9, Math.max(0.7, hi));
      const lo = hi - 0.2;
      strength = 0.05 + 0.95 * Math.pow(Math.max(0, Math.min(1, (m.z - lo) / (hi - lo))), 1.5);
      soft = true;
    } else {
      const p80 = sorted[Math.floor(sorted.length * 0.8)] || m.z || 1;
      strength = Math.min(1, m.z / p80);
    }
    // The "settled" feel the user preferred once a drop is ~20 s in: the 200-hit version, exactly as it was
    // (trigger confidence z0 against the 80th percentile of the last 200 hits, ^1.5, floor 0.12; main.js adds
    // its beat-grid accents and base motion). The new curve above is better at the START of a drop (strong
    // from the first kick), so main.js crossfades: new only for the first 10 s of a section (after >= 3 s
    // without hits, or a drop), then over 15 s to the old one.
    // which confidence the settled feel scales: the 20 ms PEAK (real kicks 0.83 / extras 0.39 strength over
    // 30 songs) or the trigger value (0.59 / 0.34: kicks barely above extras, "doesn't hit the kicks enough")
    const z0 = SETTLED_USES_PEAK ? m.z : (m.z0 != null ? m.z0 : m.z);
    // the last 40 hits (~15 s of kicks; was 200, ~1 min): same kick/extra gap over 30 songs (0.45), stronger
    // right after a pause (0.85 vs 0.80), and the previous song no longer shapes the next one's first minute
    this.zsOld.push(z0); if (this.zsOld.length > 40) this.zsOld.shift();
    const so = [...this.zsOld].sort((a, b) => a - b);
    const p80o = so[Math.floor(so.length * 0.8)] || z0 || 1;
    const strengthOld = 0.12 + 0.88 * Math.pow(Math.max(0, Math.min(1, (z0 - 0.5) / Math.max(0.05, p80o - 0.5))), 1.5);
    if (now - (this.lastMsgAt || 0) > 3000) this.sectionStart = now;
    this.lastMsgAt = now;
    // PINNED to 1 (2026-11-18 03:25, the user: "just stay with the full first version for a bit") = the
    // 200-hit feel all the time. For the crossfade (new curve at drop starts) use the computed value instead.
    const settleCrossfade = Math.max(0, Math.min(1, (now - (this.sectionStart || now) - 10000) / 15000));
    const settle = PIN_SETTLE != null ? PIN_SETTLE : settleCrossfade;
    const c = this.clock;
    let beat = false, down = false;
    if (c && c.locked) {
      const d = ((m.at - c.next) % c.period + c.period) % c.period;
      beat = Math.min(d, c.period - d) < 70;
      if (beat) {
        const k = Math.round((m.at - c.next) / c.period);
        down = ((c.pos + k) % 4 + 4) % 4 === c.down;
      }
    }
    const fire = () => { this.lastHitAt = Date.now(); this.emit('hit', { strength, strengthOld, settle, soft, beat, down, period: c ? c.period : 500 }); };
    const wait = m.at - LEAD - Date.now();
    wait > 0 ? setTimeout(fire, wait) : fire();
  }

  // seconds since the last locked beat (for "no beat for a while" -> ambient feel)
  sinceBeat() { return (Date.now() - this.lastBeatAt) / 1000; }
  sinceHit() { return (Date.now() - (this.lastHitAt || 0)) / 1000; }
}

// Dominant colours of an album cover (base64 PNG from Lively's now-playing data).
export function coverPalette(b64) {
  return new Promise(res => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = c.height = 40;
      const g = c.getContext('2d');
      g.drawImage(img, 0, 0, 40, 40);
      const d = g.getImageData(0, 0, 40, 40).data;
      const px = [];
      for (let i = 0; i < d.length; i += 4) px.push([d[i], d[i + 1], d[i + 2]]);
      res(kmeans(px, 5));
    };
    img.onerror = () => res(null);
    img.src = b64.startsWith('data:') ? b64 : 'data:image/png;base64,' + b64;
  });
}

function kmeans(px, k) {
  const w = px.map(([r, g, b]) => { const mx = Math.max(r, g, b), mn = Math.min(r, g, b); return 0.3 + (mx - mn) / (mx + 1) * 1.6 + mx / 400; });
  let c = [];
  for (let i = 0; i < k; i++) c.push(px[Math.floor((i + 0.5) / k * px.length)].slice());
  let lab = new Array(px.length).fill(0);
  for (let it = 0; it < 10; it++) {
    for (let i = 0; i < px.length; i++) {
      let best = 0, bd = 1e9;
      for (let j = 0; j < k; j++) { const d = (px[i][0] - c[j][0]) ** 2 + (px[i][1] - c[j][1]) ** 2 + (px[i][2] - c[j][2]) ** 2; if (d < bd) { bd = d; best = j; } }
      lab[i] = best;
    }
    for (let j = 0; j < k; j++) {
      let s = [0, 0, 0], ws = 0;
      for (let i = 0; i < px.length; i++) if (lab[i] === j) { s[0] += px[i][0] * w[i]; s[1] += px[i][1] * w[i]; s[2] += px[i][2] * w[i]; ws += w[i]; }
      if (ws) c[j] = [s[0] / ws, s[1] / ws, s[2] / ws];
    }
  }
  const share = c.map((_, j) => lab.reduce((a, l, i) => a + (l === j ? w[i] : 0), 0));
  return c.map((col, j) => ({ col, share: share[j] })).sort((a, b) => b.share - a.share).map(x => x.col);
}
