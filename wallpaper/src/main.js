// Pin Wall: a living collage of your own images, driven by the music and the mouse.
import { program, drawTri, drawQuad, target, resizeTarget, bindTarget, bindTex, canvasLayer, blit } from './gl.js';
import { CARD_VERT, CARD_FRAG, BG_FRAG, POST_FRAG, M } from './shaders.js';
import { makeLayout, cropFor, choosePin, rng, paletteScore } from './layout.js';
import { PinTextures } from './textures.js';
import { Overlay, makeStamp, makeBgText } from './overlay.js';
import { Music, coverPalette } from './audio.js';

const Q = new URLSearchParams(location.search);
const TEST = Q.has('test');
const canvas = document.getElementById('c');
const gl = canvas.getContext('webgl2', { antialias: false, alpha: false, preserveDrawingBuffer: TEST });
// Vivid colours: on a wide-gamut screen (the laptop's P3 OLED) Lively colour-manages the page to exact sRGB,
// which looks muted next to the same page in a browser that doesn't (sRGB values shown at the panel's full
// gamut). Tagging the canvas as Display P3 there gives that richer look on purpose. sRGB screens: unchanged.
const P3 = matchMedia('(color-gamut: p3)');
function applyGamut() {
  if (!('drawingBufferColorSpace' in gl)) return;
  const want = settings.vivid && P3.matches ? 'display-p3' : 'srgb';
  if (gl.drawingBufferColorSpace !== want) gl.drawingBufferColorSpace = want;
}
P3.addEventListener?.('change', () => applyGamut());
if (!gl) throw new Error('WebGL2 unavailable');

// ---------------------------------------------------------------- settings (Lively panel)
const settings = {
  intensity: 1.0, battery: false, clock: true, mode: null, calibrate: Q.has('calibrate'), vivid: !Q.has('srgb'),
};
window.livelyPropertyListener = (name, val) => {
  if (name === 'intensity') settings.intensity = val / 100;
  else if (name === 'battery') settings.battery = !!val;
  else if (name === 'clock') settings.clock = !!val;
  else if (name === 'mode') {
    // Lively replays saved settings on every load: only act on a real change, so the hotkey's choice
    // (kept by the listener) is not overwritten whenever the wallpaper reloads.
    const md = val === 1 ? 'ambient' : 'reactive';
    if (settings.mode !== null && md !== settings.mode) music.setMode(md);
    else if (settings.mode === null && !music.connected) music.mode = md;
    settings.mode = md;
  }
  else if (name === 'calibrate') settings.calibrate = !!val;
  else if (name === 'vivid') { settings.vivid = !!val; applyGamut(); }
};

// ---------------------------------------------------------------- palette
const DEFAULT_ACC = { hot: [255, 43, 214], pop: [182, 255, 46], cool: [34, 230, 255], deep: [123, 44, 255], tape: [255, 225, 74] };
let acc = { ...DEFAULT_ACC };
let accTarget = { ...DEFAULT_ACC };
const v3 = c => c.map(x => x / 255);

// ---------------------------------------------------------------- programs and targets
const P = {
  card: program(gl, CARD_FRAG, CARD_VERT),
  bg: program(gl, BG_FRAG),
  post: program(gl, POST_FRAG),
};
let comp = target(gl, 4, 4), frozen = target(gl, 4, 4);
const overLayer = canvasLayer(gl);
const overlay = new Overlay(overLayer);
const texs = new PinTextures(gl, 'pins/', 90);
const stampTex = [];
function stampTexture(c) {
  const t = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, t);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, c);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return t;
}

// ---------------------------------------------------------------- world state
const S = {
  pins: [], shelf: null, area: null, layout: null, cards: [],
  W: 0, H: 0, dpr: 1, kpx: 1, time: 0, last: performance.now(),
  mouse: { x: -1, y: -1, tx: 0, ty: 0, px: 0, py: 0, down: null, inside: false },
  hover: -1,
  fx: { punch: 0, split: 0, glitch: 0, gseed: 0, shatter: -1, dissolve: 1, dissolveDur: 1, flash: 0, speed: 0,
        ring: null, breath: 0, pulse: 0 },
  stamps: [],
  recent: new Set(), coverPal: null, title: null,
  bars: 0, beats: 0, nextAmbientSwap: 0, nextAmbientLayout: 0, busy: false, paused: false,
  seed: Q.has('seed') ? +Q.get('seed') : (Date.now() % 100000),
};
const music = new Music();
if (Q.get('mode')) music.mode = Q.get('mode');
window.livelyAudioListener = a => music.livelyAudio(a);
window.livelyWallpaperPlaybackChanged = d => { try { S.paused = JSON.parse(d).IsPaused; } catch (e) {} };
window.livelyCurrentTrack = d => { let o = null; try { o = JSON.parse(d); } catch (e) {} onTrack(o); };

const ambientFeel = () => music.mode === 'ambient' || music.sinceBeat() > 20;
const now = () => (Q.has('t') ? +Q.get('t') : Date.now());

// ---------------------------------------------------------------- sizing
function resize() {
  const scale = settings.battery ? 0.7 : 1;
  S.dpr = Math.min(window.devicePixelRatio || 1, 2) * scale;
  const W = Math.round(innerWidth * S.dpr), H = Math.round(innerHeight * S.dpr);
  if (W < 16 || H < 16) return false;   // no size yet (window still being created): wait
  if (W === S.W && H === S.H) return false;
  S.W = W; S.H = H;
  canvas.width = W; canvas.height = H;
  resizeTarget(gl, comp, W, H);
  resizeTarget(gl, frozen, W, H);
  const key = `${innerWidth}x${innerHeight}`;
  const sh = (S.shelfCfg && (S.shelfCfg[key] || S.shelfCfg.default)) || { band: 0, plates: [] };
  S.shelf = sh;
  S.area = { x: 0, y: sh.band, w: innerWidth, h: innerHeight - sh.band - (sh.bottom ?? 48) };
  return true;
}

// ---------------------------------------------------------------- layouts
function layoutOpts(extra = {}) {
  return { seed: S.seed++, palette: S.coverPal, recent: S.recent, ...extra };
}
function adopt(layout) {
  S.layout = layout;
  S.cards = layout.cards.map(c => ({ ...c, lift: 0, swap: null }));
  S.back = (layout.back || []).map(c => ({ ...c, lift: 0, swap: null }));
  S.marks = layout.marks || [];
  for (const c of S.back) S.recent.add(c.pin.id);
  for (const c of S.cards) S.recent.add(c.pin.id);
  if (S.recent.size > 80) S.recent = new Set([...S.recent].slice(-60));
}
const layoutPins = l => [...l.cards, ...(l.back || [])].map(c => c.pin);
async function prepare(extra) {
  const l = makeLayout(S.pins, S.area, layoutOpts(extra));
  await texs.ensure(layoutPins(l));
  return l;
}
// The next wall is built and its pictures loaded ahead of time, so a drop can shatter into it at once
// (loading a whole wall at the moment of the drop made the break start late and stutter).
async function prepNext() {
  if (S.nextPrep || !S.area || S.empty) return;
  S.nextPrep = true;
  const gen = S.gen = (S.gen || 0);
  try {
    const pal = S.coverPal, area = S.area;
    const l = makeLayout(S.pins, area, layoutOpts());
    await texs.ensure(layoutPins(l), 8000);
    l.forPal = pal; l.forArea = area;
    S.next = (pal === S.coverPal && area === S.area && gen === S.gen) ? l : null;
  } finally { S.nextPrep = false; }
}
async function relayout(kind = 'dissolve', extra = {}) {
  if (S.busy || !S.layout) return;
  S.busy = true;
  const tp = performance.now();
  let l = null;
  const nx = S.next;
  if (nx && !extra.template && nx.forPal === S.coverPal && nx.forArea === S.area && texs.ready(layoutPins(nx))) l = nx;
  if (!l) l = await prepare(extra);
  S.next = null; S.gen = (S.gen || 0) + 1;
  setTimeout(prepNext, 4000);
  if (S.perf) S.perf.prep = Math.round(performance.now() - tp);
  freeze();
  adopt(l);
  if (kind === 'shatter') { S.fx.shatter = 0; S.fx.flash = 1; S.fx.speed = 1; }
  else { S.fx.dissolve = 0; S.fx.dissolveDur = kind === 'slow' ? 2.8 : 0.9; }
  S.busy = false;
}
function freeze() { blit(gl, comp.tex, frozen); }

function swapCard(i, kind = 0, dir = [1, 0], dur = 0.7) {
  const c = S.cards[i];
  if (!c || c.swap) return;
  const used = new Set(S.cards.map(x => x.pin.id));
  for (const id of S.recent) used.add(id);
  const slot = { w: c.w, h: c.h, mode: c.kind, role: c.role };
  const pin = choosePin(S.pins, slot, used, { palette: S.coverPal }, rng(S.seed++));
  if (!pin) return;
  const e = texs.get(pin);
  const start = () => {
    c.swap = { pin, crop: c.kind === 'win' ? cropFor(pin, c.w - 8 * S.layout.k, c.h - 40 * S.layout.k) : cropFor(pin, c.w, c.h),
               t0: S.time, dur, kind, dir };
    S.recent.add(pin.id);
  };
  e.ready ? start() : e.promise.then(start);
}
function finishSwaps() {
  for (const c of S.cards) {
    if (c.swap && S.time - c.swap.t0 >= c.swap.dur) { c.pin = c.swap.pin; c.crop = c.swap.crop; c.swap = null; }
  }
}
function randomCard(excludeHero = true) {
  const idx = S.cards.map((c, i) => i).filter(i => !S.cards[i].swap && !(excludeHero && S.cards[i].role));
  return idx.length ? idx[Math.floor(Math.random() * idx.length)] : -1;
}

// ---------------------------------------------------------------- music events
// beats keep the bar count and the edit-style changes; they only act while kicks are really playing
music.on('beat', b => {
  if (music.mode !== 'reactive' || S.paused) return;
  S.beats++;
  if (!b.down || music.sinceHit() > 2) return;
  S.bars++;
  const I = settings.intensity;
  if (S.bars % 8 === 0) {
    for (let n = 0; n < 3; n++) setTimeout(() => swapCard(randomCard()), n * b.period / 2);
    S.fx.glitch = Math.max(S.fx.glitch, 0.75 * I); S.fx.gseed = Math.random() * 100;
  } else swapCard(randomCard(), 0, [1, 0], Math.min(0.9, b.period * 1.6 / 1000));
  if (S.bars % 32 === 0) relayout('fast');
});

// hits: only on the eighth notes where kicks land, only while kicks are present
music.on('hit', h => {
  if (music.mode !== 'reactive' || S.paused) return;
  const I = settings.intensity;
  S.hits = (S.hits || 0) + 1;
  if (h.soft) {
    // KickNet hits: strength is the whole story (0.05 = near nothing, 1 = full), so EVERY effect scales with it,
    // base amounts included (they used to fire at a fixed minimum on every hit, so "no kick" was never 0).
    // Full strength gives what a full hit always gave. Not damped off the beat-clock grid (after a drop the
    // clock needs 10-30 s to re-lock); downbeat accents only when the clock is locked and agrees.
    // Two feels, crossfaded by h.settle (0 for the first 10 s of a drop/section, 1 after 25 s):
    //  start  : strength from the 30 s curve, every effect proportional (strong from the first kick)
    //  settled: the 200-hit version the user preferred once a drop runs (beat-grid accents, base motion)
    const w = h.settle || 0;
    const a = h.strength;
    const ao = Math.max(0.12, h.strengthOld != null ? h.strengthOld : a) * (h.beat ? 1 : 0.75);
    const mix = (n, o) => n * (1 - w) + o * w;
    S.fx.punch = Math.max(S.fx.punch, mix((0.038 + (h.down ? 0.014 : 0)) * a, 0.012 + 0.026 * ao + (h.down ? 0.014 : 0)) * I);
    S.fx.pulse = Math.max(S.fx.pulse, mix(a, 1));
    S.fx.bounce = Math.max(S.fx.bounce, mix(Math.min(1.4, (1.1 + (h.down ? 0.3 : 0)) * a), Math.min(1.4, 0.5 + 0.6 * ao + (h.down ? 0.3 : 0))) * I);
    S.fx.beatGlow = Math.max(S.fx.beatGlow || 0, mix(a, 1));
    const am = mix(a, ao);
    if (am > 0.3) S.rayTarget = (S.rayTarget || 0) + (h.down ? 2 : 1) / 30;   // the sunburst steps one ray per confident kick
    S.fx.split = Math.max(S.fx.split, mix((h.down ? 8.5 : 4.5) * a, 1.5 + (h.down ? 7 : 3) * ao) * I);
    if (h.down) S.fx.flash = Math.max(S.fx.flash, mix((0.1 + 0.08 * a) * a, 0.1 + 0.08 * ao));
    if (!h.beat && am > 0.35 && Math.random() < 0.35) { S.fx.glitch = Math.max(S.fx.glitch, 0.25 * I); S.fx.gseed = Math.random() * 100; }
    return;
  }
  // the older flux-trigger hits (nn=0): a 0.4 floor and off-beat damping
  const a = Math.max(0.4, h.strength) * (h.beat ? 1 : 0.75);
  S.fx.punch = Math.max(S.fx.punch, (0.012 + 0.026 * a + (h.down ? 0.014 : 0)) * I);
  S.fx.pulse = 1;
  S.fx.bounce = Math.min(1.4, 0.5 + 0.6 * a + (h.down ? 0.3 : 0)) * I;
  S.fx.beatGlow = 1;
  if (a > 0.3) S.rayTarget = (S.rayTarget || 0) + (h.down ? 2 : 1) / 30;
  S.fx.split = Math.max(S.fx.split, (1.5 + (h.down ? 7 : 3) * a) * I);
  if (h.down) S.fx.flash = Math.max(S.fx.flash, 0.1 + 0.08 * a);
  if (!h.beat && a > 0.35 && Math.random() < 0.35) { S.fx.glitch = Math.max(S.fx.glitch, 0.25 * I); S.fx.gseed = Math.random() * 100; }
});

music.on('drop', m => {
  if ((music.mode !== 'reactive' && !(m && m.test)) || !S.layout) return;
  if (m && m.test) perfStart(m.fxonly ? 'shatter-only' : 'drop');
  if (m && m.fxonly) { freeze(); S.fx.shatter = 0; S.fx.flash = 1; S.fx.speed = 1; return; }
  relayout('shatter');   // no stamp: the user liked the break better without the yellow ドン (2026-11-18)
});
music.on('mode', () => { S.fx.dissolve = 0; S.fx.dissolveDur = 2.0; freeze(); });

async function onTrack(o) {
  if (!o || !o.Title) return;
  const title = { text: o.Title, artist: o.Artist || '', t0: Date.now(), chips: [] };
  if (o.Thumbnail) {
    const pal = await coverPalette(o.Thumbnail);
    if (pal) {
      S.coverPal = pal;
      const vivid = pal.filter(c => sat(c) > 0.18).map(c => boost(c));
      while (vivid.length < 3) vivid.push([DEFAULT_ACC.hot, DEFAULT_ACC.pop, DEFAULT_ACC.deep][vivid.length]);
      accTarget = { ...accTarget, hot: vivid[0], pop: vivid[1] || DEFAULT_ACC.pop, deep: vivid[2] || DEFAULT_ACC.deep };
      title.chips = pal.slice(0, 5).map(c => c.map(Math.round));
    }
  }
  S.title = title;
  if (o.Thumbnail) {
    const img = new Image();
    img.onload = () => {
      const t = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      if (S.cover) gl.deleteTexture(S.cover.tex);
      S.cover = { tex: t, aspect: img.width / img.height, t0: S.time };
    };
    img.src = o.Thumbnail.startsWith('data:') ? o.Thumbnail : 'data:image/png;base64,' + o.Thumbnail;
  } else if (S.cover) { gl.deleteTexture(S.cover.tex); S.cover = null; }
  relayout(ambientFeel() ? 'slow' : 'fast');
}
function sat(c) { const mx = Math.max(...c), mn = Math.min(...c); return (mx - mn) / (mx + 1); }
function boost(c) {
  // push a cover colour to neon: keep its hue, force high saturation and brightness
  const [r, g, b] = c.map(v => v / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d > 1e-4) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  h = (h * 60 + 360) % 360;
  const sv = Math.max(0.78, d / (mx || 1)), vv = Math.max(0.95, mx);
  const k = n => { const kk = (n + h / 60) % 6; return vv - vv * sv * Math.max(0, Math.min(kk, 4 - kk, 1)); };
  return [k(5), k(3), k(1)].map(x => Math.round(x * 255));
}

// ---------------------------------------------------------------- the music toggle button
// A small plate on the desktop: click it to switch between reacting to the music and a calm wall.
function buttonRect() {
  const w = 268, h = 66;
  if (S.shelf && S.shelf.band > 0) return { x: innerWidth - 44 - w, y: (S.shelf.band - h) / 2, w, h };
  return { x: innerWidth - 26 - w, y: S.area.y + 20, w, h };
}
let btnTex = { key: '', tex: null };
function buttonTexture(reactive, hover) {
  const key = `${reactive}|${hover}|${S.dpr}`;
  if (btnTex.key === key) return btnTex.tex;
  const r = buttonRect(), k = S.dpr * 2;           // draw at 2x for crisp text
  const c = document.createElement('canvas');
  c.width = Math.round((r.w + 24) * k); c.height = Math.round((r.h + 24) * k);
  const g = c.getContext('2d');
  g.scale(k, k); g.translate(12, 12);
  const lime = '#b6ff2e', pink = '#ff2bd6', violet = '#7b2cff';
  const accent = reactive ? lime : violet;
  const rr = (x, y, w, h, rad) => { g.beginPath(); g.moveTo(x + rad, y); g.arcTo(x + w, y, x + w, y + h, rad); g.arcTo(x + w, y + h, x, y + h, rad); g.arcTo(x, y + h, x, y, rad); g.arcTo(x, y, x + w, y, rad); g.closePath(); };
  // plate: print-out-of-register shadow, dark fill, accent outline
  rr(5, 5, r.w, r.h, 14); g.fillStyle = reactive ? pink : '#22e6ff'; g.globalAlpha = 0.85; g.fill(); g.globalAlpha = 1;
  rr(0, 0, r.w, r.h, 14); g.fillStyle = hover ? '#1c1030' : '#0e0818'; g.fill();
  g.lineWidth = hover ? 3 : 2; g.strokeStyle = accent; g.stroke();
  // fine hatch inside
  g.save(); rr(0, 0, r.w, r.h, 14); g.clip(); g.strokeStyle = 'rgba(255,255,255,0.05)'; g.lineWidth = 1;
  for (let x = -r.h; x < r.w; x += 6) { g.beginPath(); g.moveTo(x, r.h); g.lineTo(x + r.h, 0); g.stroke(); } g.restore();
  // tape on the corner
  g.save(); g.translate(18, -2); g.rotate(-0.35); g.fillStyle = 'rgba(255,225,74,0.8)'; g.fillRect(-24, -7, 48, 14); g.restore();
  // icon well (the live meter is drawn into it by GL)
  rr(14, 13, 40, 40, 8); g.fillStyle = '#000'; g.fill(); g.strokeStyle = 'rgba(255,255,255,0.25)'; g.lineWidth = 1; g.stroke();
  // label
  g.font = '700 17px "Space Mono", Consolas, monospace'; g.textBaseline = 'middle';
  g.fillStyle = '#fff'; g.fillText(reactive ? 'REACTIVE' : 'AMBIENT', 66, r.h / 2 - 9);
  g.font = '700 11px "Space Mono", Consolas, monospace'; g.fillStyle = reactive ? lime : '#b9a3ff';
  g.fillText(reactive ? 'MOVES WITH THE MUSIC' : 'CALM, NO BEAT HITS', 66, r.h / 2 + 12);
  // switch
  const sx = r.w - 62, sy = r.h / 2 - 13;
  rr(sx, sy, 48, 26, 13); g.fillStyle = reactive ? lime : '#2a1a44'; g.fill();
  g.beginPath(); g.arc(reactive ? sx + 35 : sx + 13, sy + 13, 10, 0, Math.PI * 2); g.fillStyle = reactive ? '#000' : '#b9a3ff'; g.fill();
  if (btnTex.tex) gl.deleteTexture(btnTex.tex);
  btnTex = { key, tex: stampTexture(c), w: c.width / k, h: c.height / k };
  return btnTex.tex;
}
function inButton(x, y) { const r = buttonRect(); return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h; }
function toggleMusicMode() {
  const next = music.mode === 'reactive' ? 'ambient' : 'reactive';
  music.setMode(next);
  settings.mode = next;
  S.btnPress = S.time;
}

// ---------------------------------------------------------------- mouse
function cardAt(x, y) {
  for (let i = S.cards.length - 1; i >= 0; i--) {
    const c = S.cards[i];
    const dx = x - c.cx, dy = y - c.cy, cs = Math.cos(-c.rot), sn = Math.sin(-c.rot);
    const lx = dx * cs - dy * sn, ly = dx * sn + dy * cs;
    if (Math.abs(lx) < c.w / 2 && Math.abs(ly) < c.h / 2) return i;
  }
  return -1;
}
addEventListener('pointermove', e => {
  S.moves = (S.moves || 0) + 1;
  S.mouse.x = e.clientX; S.mouse.y = e.clientY; S.mouse.inside = true;
  S.mouse.tx = e.clientX / innerWidth - 0.5; S.mouse.ty = e.clientY / innerHeight - 0.5;
});
addEventListener('pointerdown', e => { S.mouse.down = { x: e.clientX, y: e.clientY, card: cardAt(e.clientX, e.clientY), t: S.time }; });
addEventListener('pointerup', e => {
  const d = S.mouse.down; S.mouse.down = null;
  if (d && inButton(d.x, d.y) && inButton(e.clientX, e.clientY)) { toggleMusicMode(); return; }
  if (!d || d.y < S.area.y) return;   // the icon shelf never reacts to clicks
  const dx = e.clientX - d.x, dy = e.clientY - d.y, dist = Math.hypot(dx, dy);
  if (dist > 60 && d.card >= 0) swapCard(d.card, 1, [dx / dist, dy / dist], 0.55);
  else if (dist < 10) click(e.clientX, e.clientY);
});
function click(x, y) {
  addStamp(x, y, Math.random() < 0.5 ? 'ドン' : '', 1);
  S.fx.ring = { x, y, t0: S.time };
  S.fx.punch = Math.max(S.fx.punch, 0.012);
}
function addStamp(x, y, text, scale) {
  const key = text || '_';
  if (!stampTex[key]) stampTex[key] = stampTexture(makeStamp(text));
  S.stamps.push({ x, y, t0: S.time, tex: stampTex[key], rot: (Math.random() - 0.5) * 0.5, scale });
}

// ---------------------------------------------------------------- print marks
const markCache = {};
function markTex(kind) {
  if (markCache[kind]) return markCache[kind];
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  g.translate(64, 64);
  if (kind === 'spark') {          // 4-point sparkle
    g.fillStyle = '#ffffff';
    g.beginPath();
    for (let i = 0; i < 8; i++) { const r = i % 2 ? 9 : 60, a = i * Math.PI / 4 - Math.PI / 2; g.lineTo(Math.cos(a) * r, Math.sin(a) * r); }
    g.closePath(); g.fill();
  } else if (kind === 'reg') {     // registration mark
    g.strokeStyle = '#ffffff'; g.lineWidth = 5;
    g.beginPath(); g.arc(0, 0, 30, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.moveTo(-56, 0); g.lineTo(56, 0); g.moveTo(0, -56); g.lineTo(0, 56); g.stroke();
  } else if (kind === 'burst') {   // small lime starburst
    g.fillStyle = '#b6ff2e'; g.beginPath();
    for (let i = 0; i < 24; i++) { const r = i % 2 ? 26 : 58, a = i * Math.PI / 12; g.lineTo(Math.cos(a) * r, Math.sin(a) * r); }
    g.closePath(); g.fill();
  } else if (kind === 'barcode') {
    g.fillStyle = '#ffffff'; g.fillRect(-60, -24, 120, 48);
    g.fillStyle = '#000000';
    let x = -54; let i = 0;
    while (x < 54) { const w = [2, 4, 2, 6, 3][i++ % 5]; g.fillRect(x, -18, w, 36); x += w + [3, 2, 4][i % 3]; }
  } else {                         // plus
    g.fillStyle = '#ff2bd6'; g.fillRect(-8, -50, 16, 100); g.fillRect(-50, -8, 100, 16);
  }
  return (markCache[kind] = stampTexture(c));
}

// solid rectangle in canvas px (top-left x, y)
function drawRect(x, y, w, h, rgb, alpha = 1) {
  const u = P.card.u;
  gl.uniform2f(u.uCenter, x + w / 2, y + h / 2);
  gl.uniform2f(u.uHalf, w / 2, h / 2);
  gl.uniform1f(u.uPad, 0); gl.uniform1f(u.uRot, 0); gl.uniform1f(u.uScale, 1);
  gl.uniform1i(u.uMode, M.PLAIN);
  gl.uniform4f(u.uTint, rgb[0], rgb[1], rgb[2], 1);
  gl.uniform1f(u.uAlpha, alpha);
  drawQuad(gl);
}

// background outline type: the artist's name, or the day of the week when nothing plays
let bgText = { key: '', tex: null, w: 0, h: 0 };
function bgTextFor(px) {
  const DAYS = ['SUNDAY', 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY'];
  const word = (S.title && (S.title.artist || S.title.text)) || DAYS[new Date().getDay()];
  const key = word + '|' + Math.round(px);
  if (bgText.key !== key) {
    const c = makeBgText(word, px);
    if (bgText.tex) gl.deleteTexture(bgText.tex);
    bgText = { key, tex: stampTexture(c), w: c.width, h: c.height };
  }
  return bgText;
}

// ---------------------------------------------------------------- drawing
function setAcc(prog) {
  const u = prog.u;
  if (u.uAcc1) gl.uniform3fv(u.uAcc1, v3(acc.hot));
  if (u.uAcc2) gl.uniform3fv(u.uAcc2, v3(acc.deep));
  if (u.uAcc3) gl.uniform3fv(u.uAcc3, v3(acc.tape));
  if (u.uBase) gl.uniform3fv(u.uBase, [0.027, 0.016, 0.043]);
}

function drawCard(c, i, par) {
  const u = P.card.u, kp = S.kpx, unit = kp * S.layout.k;
  const lift = c.lift;
  // every picture floats on its own slow path and sways a little, so the wall is always alive
  const L = S.layout.k, sd = c.seed, T = S.time;
  const amp = c.back ? 1.3 : (c.role ? 0.7 : 1);
  const fx_ = (Math.sin(T * 0.42 + sd) * 14 + Math.sin(T * 0.19 + sd * 2.1) * 9) * L * amp;
  const fy_ = (Math.cos(T * 0.35 + sd * 1.3) * 11 + Math.sin(T * 0.23 + sd * 0.7) * 7) * L * amp;
  const sway = Math.sin(T * 0.31 + sd * 1.7) * 0.022 * amp;
  const cx = (c.cx + fx_ - par.x * c.depth) * kp, cy = (c.cy + fy_ - par.y * c.depth) * kp;
  gl.uniform2f(u.uCenter, cx, cy);
  gl.uniform2f(u.uHalf, c.w / 2 * kp, c.h / 2 * kp);
  gl.uniform1f(u.uPad, 70 * unit);
  gl.uniform1f(u.uRot, c.rot + sway + lift * 0.035);
  const bounce = S.fx.bounce * (c.back ? 0.02 : (c.role ? 0.045 : 0.03 + 0.03 * c.depth));
  gl.uniform1f(u.uScale, 1 + lift * 0.07 + bounce + (c.role ? S.fx.breath * 1.5 : S.fx.breath * 0.6));
  gl.uniform1f(u.uUnit, unit);
  gl.uniform1i(u.uMode, c.mode);
  gl.uniform1f(u.uSeed, c.seed);
  bindTex(gl, 0, texs.tex(c.pin));
  gl.uniform4fv(u.uCrop, c.crop);
  if (c.swap) {
    bindTex(gl, 1, texs.tex(c.swap.pin));
    gl.uniform4fv(u.uCropB, c.swap.crop);
    gl.uniform1f(u.uSwap, Math.min(1, (S.time - c.swap.t0) / c.swap.dur));
    gl.uniform1i(u.uSwapKind, c.swap.kind);
    gl.uniform2fv(u.uSwapDir, c.swap.dir);
  } else gl.uniform1f(u.uSwap, 0);
  gl.uniform1f(u.uFoil, lift);
  const mx = (S.mouse.x - c.cx), my = (S.mouse.y - c.cy), cs = Math.cos(-c.rot), sn = Math.sin(-c.rot);
  gl.uniform2f(u.uLight, (mx * cs - my * sn) * kp, (mx * sn + my * cs) * kp);
  gl.uniform1f(u.uAlpha, 1);
  gl.uniform1f(u.uShadow, c.back ? 0.7 : 1);
  gl.uniform1f(u.uDim, c.back ? 0.6 + 0.25 * S.fx.pulse : 1);
  gl.uniform1f(u.uLift, lift);
  drawQuad(gl);
  if (c.tape) drawTapes(c, cx, cy, unit);
}

function drawTapes(c, cx, cy, unit) {
  const u = P.card.u, kp = S.kpx;
  const strips = [[-0.22, -0.5, -6], [0.24, 0.5, 4]];
  for (const [fx, fy, deg] of strips) {
    const lx = fx * c.w * kp, ly = fy * c.h * kp;
    const cs = Math.cos(c.rot), sn = Math.sin(c.rot);
    gl.uniform2f(u.uCenter, cx + lx * cs - ly * sn, cy + lx * sn + ly * cs);
    gl.uniform2f(u.uHalf, 65 * unit, 17 * unit);
    gl.uniform1f(u.uPad, 0);
    gl.uniform1f(u.uRot, c.rot + deg * Math.PI / 180);
    gl.uniform1f(u.uScale, 1);
    gl.uniform1i(u.uMode, M.TAPE);
    gl.uniform1f(u.uSeed, c.seed + fx);
    drawQuad(gl);
  }
}

function drawSprite(tex, x, y, size, rot, alpha, hh) {
  const u = P.card.u;
  gl.uniform2f(u.uCenter, x, y);
  gl.uniform2f(u.uHalf, size, hh ?? size);
  gl.uniform1f(u.uPad, 0);
  gl.uniform1f(u.uRot, rot);
  gl.uniform1f(u.uScale, 1);
  gl.uniform1i(u.uMode, M.SPRITE);
  gl.uniform1f(u.uAlpha, alpha);
  gl.uniform4f(u.uTint, 0, 0, 0, 0);
  bindTex(gl, 0, tex);
  drawQuad(gl);
}

// perf probe: after a test drop (or any shatter), record frame gaps, CPU cost per frame and long tasks for
// 2.5 s and report them to the listener log (the 'perf' stat)
function perfStart(tag) {
  const P = S.perf = { tag, t0: performance.now(), gaps: [], cost: [], long: [], prep: null, last: performance.now() };
  try {
    P.obs = new PerformanceObserver(l => { for (const e of l.getEntries()) P.long.push(Math.round(e.duration)); });
    P.obs.observe({ entryTypes: ['longtask'] });
  } catch (_) {}
  setTimeout(() => {
    if (P.obs) P.obs.disconnect();
    S.perf = null;
    const st = a => { const s = [...a].sort((x, y) => x - y); return s.length ? { med: +s[s.length >> 1].toFixed(1), p95: +s[Math.floor(s.length * 0.95)].toFixed(1), max: +s[s.length - 1].toFixed(1) } : null; };
    const msg = { type: 'stat', perf: P.tag, w: innerWidth, h: innerHeight, frames: P.gaps.length, prep_ms: P.prep,
                  gap: st(P.gaps), over34: P.gaps.filter(x => x > 34).length, cost: st(P.cost), long: P.long };
    if (music.connected) music.ws.send(JSON.stringify(msg));
    window.__lastPerf = msg;
  }, 2500);
}
function frame() {
  requestAnimationFrame(frame);
  if (S.perf) { const t = performance.now(); S.perf.gaps.push(t - S.perf.last); S.perf.last = t; }
  const a = performance.now();
  texs.pump();
  if (S.next && (S.frames || 0) % 300 === 0) texs.touch(layoutPins(S.next));   // keep it out of the LRU's reach
  frameBody();
  if (S.perf) S.perf.cost.push(performance.now() - a);
}
function frameBody() {
  if (S.paused && !TEST) return;
  const t = performance.now();
  let dt = Math.min(0.05, (t - S.last) / 1000);
  S.last = t;
  if (settings.battery && dt < 1 / 31 && !TEST) return;
  S.time += dt;
  if (resize() && S.layout) adopt(makeLayout(S.pins, S.area, layoutOpts({ template: S.layout.tmplIndex })));
  if (!S.layout) return;
  music.update(dt);
  const fx = S.fx;
  const decay = r => Math.exp(-dt * r);
  fx.punch *= decay(9); fx.split *= decay(10); fx.glitch *= decay(7); fx.pulse *= decay(5);
  fx.flash *= decay(5); fx.speed *= decay(2.5);
  fx.bounce = (fx.bounce || 0) * decay(7); fx.beatGlow = (fx.beatGlow || 0) * decay(6);
  S.rayRot = (S.rayRot || 0) + ((S.rayTarget || 0) - (S.rayRot || 0)) * (1 - Math.exp(-dt * 14));
  if (fx.shatter >= 0) { fx.shatter += dt; if (fx.shatter > 1.5) fx.shatter = -1; }
  if (fx.dissolve < 1) fx.dissolve = Math.min(1, fx.dissolve + dt / fx.dissolveDur);
  const calm = music.mode !== 'reactive';
  const lv = calm ? { b: 0, m: 0, h: 0 } : music.levels;   // ambient: the music drives nothing
  const amb = ambientFeel();
  fx.breath = amb ? 0.003 * Math.sin(S.time * 0.35) : 0.012 * lv.b * settings.intensity;
  // (no hits from bass alone: a swell in a breakdown is not a kick)
  for (const key of Object.keys(acc)) acc[key] = acc[key].map((v, i) => v + (accTarget[key][i] - v) * (1 - Math.exp(-dt * 1.5)));

  // ambient life: one picture melts into another about once a minute, a new wall every few minutes
  if (amb && !TEST) {
    if (!S.nextAmbientSwap) S.nextAmbientSwap = S.time + 40 + Math.random() * 25;
    if (!S.nextAmbientLayout) S.nextAmbientLayout = S.time + 240;
    if (S.time > S.nextAmbientSwap) { swapCard(randomCard(false), 0, [1, 0], 1.8); S.nextAmbientSwap = S.time + 50 + Math.random() * 25; }
    if (S.time > S.nextAmbientLayout) { relayout('slow'); S.nextAmbientLayout = S.time + 220 + Math.random() * 60; }
  }
  finishSwaps();

  // parallax and hover
  const m = S.mouse;
  const pk = amb ? 0.6 : 1;
  m.px += (m.tx * 40 * pk - m.px) * (1 - Math.exp(-dt * 3));
  m.py += (m.ty * 26 * pk - m.py) * (1 - Math.exp(-dt * 3));
  const drift = { x: Math.sin(S.time * 0.11) * 26, y: Math.cos(S.time * 0.08) * 16 };
  const par = { x: m.px + drift.x, y: m.py + drift.y };
  S.hover = m.inside && m.y > S.area.y ? cardAt(m.x, m.y) : -1;
  if (Q.has('hover')) { const [hx, hy] = Q.get('hover').split(',').map(Number); S.mouse.x = hx; S.mouse.y = hy; S.hover = cardAt(hx, hy); }
  S.cards.forEach((c, i) => { c.lift += ((i === S.hover ? 1 : 0) - c.lift) * (1 - Math.exp(-dt * (TEST ? 60 : 9))); });

  texs.tick(S.cards.filter(c => c.pin.anim).map(c => c.pin.id));

  // ---- collage into comp ----
  const kp = S.kpx = S.dpr;
  bindTarget(gl, comp);
  gl.disable(gl.BLEND);
  gl.useProgram(P.bg.p);
  const hero = S.cards.find(c => c.role === 'hero') || S.cards[0] || { cx: S.area.x + S.area.w / 2, cy: S.area.y + S.area.h / 2 };
  let u = P.bg.u;
  gl.uniform2f(u.uRes, S.W, S.H);
  gl.uniform1f(u.uTime, S.time);
  gl.uniform1f(u.uUnit, kp * S.layout.k);
  gl.uniform1f(u.uHigh, lv.h);
  gl.uniform1f(u.uBass, lv.b);
  gl.uniform2f(u.uCenter, hero.cx * kp, hero.cy * kp);
  gl.uniform2f(u.uDots, S.layout.dots[0] * S.W, (S.area.y + S.layout.dots[1] * S.area.h) * kp);
  gl.uniform2f(u.uPar, -par.x * kp * 0.3, -par.y * kp * 0.3);
  gl.uniform1f(u.uRayRot, S.rayRot || 0);
  gl.uniform1f(u.uBeat, fx.beatGlow || 0);
  setAcc(P.bg);
  gl.uniform3fv(u.uAcc2, v3(acc.cool));
  gl.uniform3fv(u.uRingCol, v3(acc.pop));
  drawTri(gl);

  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.useProgram(P.card.p);
  u = P.card.u;
  gl.uniform2f(u.uRes, S.W, S.H);
  gl.uniform1i(u.uTex, 0); gl.uniform1i(u.uTexB, 1);
  gl.uniform1f(u.uTime, S.time);
  gl.uniform1f(u.uShimmer, lv.h * (amb ? 0.3 : 1));
  setAcc(P.card);
  gl.uniform3fv(u.uInk, [0.05, 0.02, 0.12]);
  gl.uniform3fv(u.uRingCol, v3(acc.pop));
  for (const c of S.back || []) drawCard(c, -1, par);
  {
    const bt = bgTextFor(330 * kp * S.layout.k);
    const yC = (S.area.y + S.area.h * 0.47 - par.y * 0.15) * kp;
    const speed = (amb ? 14 : 26) * kp * S.layout.k;
    let x0 = -((S.time * speed + par.x * 0.15 * kp) % bt.w);
    for (let x = x0; x < S.W; x += bt.w) drawSprite(bt.tex, x + bt.w / 2, yC, bt.w / 2, 0, 0.55 + 0.45 * (fx.beatGlow || 0), bt.h / 2);
  }
  const order = S.cards.map((c, i) => i).sort((a, b) => (a === S.hover) - (b === S.hover));
  for (const i of order) drawCard(S.cards[i], i, par);
  // print marks: twinkle with the highs, pop on the beat
  for (const mk of S.marks || []) {
    const tex = markTex(mk.kind);
    const tw = 1 + 0.35 * (fx.beatGlow || 0) + 0.25 * lv.h * Math.sin(S.time * 7 + mk.phase);
    const spin = mk.kind === 'spark' ? Math.sin(S.time * 0.6 + mk.phase) * 0.3 : 0;
    drawSprite(tex, (mk.x - par.x * mk.depth) * kp, (mk.y - par.y * mk.depth) * kp, mk.size * kp * tw, mk.rot + spin,
      0.85 + 0.15 * Math.sin(S.time * 2 + mk.phase));
  }
  gl.disable(gl.BLEND);

  // ---- overlay text ----
  const titleCorner = S.layout.title, clockCorner = S.layout.clock;
  const changed = overlay.draw({
    W: S.W, H: S.H, k: kp * S.layout.k, area: { x: S.area.x * kp, y: S.area.y * kp, w: S.area.w * kp, h: S.area.h * kp },
    corner: clockCorner, titleCorner, acc: [acc.hot, acc.hot, [182, 255, 46], acc.deep], showClock: settings.clock, now: now(), title: S.title,
    bpm: music.clock && music.clock.locked ? music.clock.bpm : 0, empty: S.empty,
  });
  if (changed) overLayer.upload();

  // ---- final ----
  bindTarget(gl, null);
  gl.useProgram(P.post.p);
  u = P.post.u;
  bindTex(gl, 0, comp.tex); gl.uniform1i(u.uComp, 0);
  bindTex(gl, 1, frozen.tex); gl.uniform1i(u.uFrozen, 1);
  bindTex(gl, 2, overLayer.tex); gl.uniform1i(u.uOver, 2);
  gl.uniform2f(u.uRes, S.W, S.H);
  gl.uniform1f(u.uTime, S.time);
  gl.uniform1f(u.uUnit, kp * S.layout.k);
  gl.uniform1f(u.uPunch, fx.punch);
  gl.uniform1f(u.uBreath, fx.breath);
  gl.uniform1f(u.uSplit, fx.split * kp);
  gl.uniform1f(u.uGlitch, fx.glitch);
  gl.uniform1f(u.uGlitchSeed, fx.gseed);
  const shake = fx.punch * 600 * kp;
  gl.uniform2f(u.uShake, (Math.random() - 0.5) * shake, (Math.random() - 0.5) * shake);
  gl.uniform1f(u.uShatter, fx.shatter);
  if (fx.shatter >= 0) {
    // shard layout (same recipe the shader used to compute per pixel): seed, flight vector, spin
    const fr = x => x - Math.floor(x);
    const h11 = q => { q = fr(q * 0.1031); q *= q + 33.33; q *= q + q; return fr(q); };
    const unit = kp * S.layout.k, cx = S.W / 2, cy = (S.H + S.shelf.band * kp) / 2;
    const A = S.shardA || (S.shardA = new Float32Array(104)), R = S.shardR || (S.shardR = new Float32Array(26));
    for (let i = 0; i < 26; i++) {
      const sx = h11(i * 3.7 + 1) * S.W, sy = h11(i * 9.1 + 2) * S.H;
      let dx = sx - cx + 1e-3, dy = sy - cy + 1e-3;
      const l = Math.hypot(dx, dy); dx /= l; dy /= l;
      const sp = (180 + 520 * h11(i * 5.3)) * unit;
      A.set([sx, sy, dx * sp, dy * sp], i * 4);
      R[i] = (h11(i * 1.3) - 0.5) * 0.9;
    }
    gl.uniform4fv(u.uShardA, A);
    gl.uniform1fv(u.uShardR, R);
  }
  gl.uniform1f(u.uDissolve, fx.dissolve);
  gl.uniform1f(u.uFlash, fx.flash * 0.85);
  gl.uniform1f(u.uSpeed, fx.speed);
  if (fx.ring) {
    const rt = S.time - fx.ring.t0;
    if (rt > 0.7) fx.ring = null;
    else gl.uniform4f(u.uRing, fx.ring.x * kp, fx.ring.y * kp, rt * 900 * kp, 1 - rt / 0.7);
  }
  if (!fx.ring) gl.uniform4f(u.uRing, 0, 0, 0, 0);
  gl.uniform1f(u.uShelfH, S.shelf.band * kp);
  gl.uniform1f(u.uBottom, (S.shelf.bottom ?? 48) * kp);
  gl.uniform1f(u.uPulse, fx.pulse * 0.6);
  const plates = new Float32Array(24);
  const ps = S.shelf.plates || [];
  ps.slice(0, 6).forEach((p, i) => {
    const hov = m.inside && m.y < S.shelf.band && m.x >= p[0] && m.x <= p[1];
    p.glow = (p.glow || 0) + ((hov ? 1 : 0) - (p.glow || 0)) * (1 - Math.exp(-dt * 10));
    plates.set([p[0] * kp, p[1] * kp, p.glow, 0], i * 4);
  });
  gl.uniform4fv(u.uPlates, plates);
  gl.uniform1i(u.uNPlates, Math.min(6, ps.length));
  gl.uniform2f(u.uPlateY, (S.shelf.plateY ? S.shelf.plateY[0] : 4) * kp, (S.shelf.plateY ? S.shelf.plateY[1] : S.shelf.band - 8) * kp);
  setAcc(P.post);
  gl.uniform3fv(u.uAcc1, v3(acc.pop));
  gl.uniform1f(u.uCalib, settings.calibrate ? 1 : 0);
  drawTri(gl);

  // ---- the music toggle button (with a live mini meter in its icon well) ----
  {
    const r = buttonRect();
    const reactive = music.mode === 'reactive';
    const hov = m.inside && inButton(m.x, m.y);
    const tex = buttonTexture(reactive, hov);
    const press = S.btnPress ? Math.max(0, 1 - (S.time - S.btnPress) / 0.25) : 0;
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(P.card.p); gl.uniform2f(P.card.u.uRes, S.W, S.H);
    const sc = (1 + (hov ? 0.03 : 0) - press * 0.06) * kp;
    drawSprite(tex, (r.x + r.w / 2 + 6) * kp, (r.y + r.h / 2 + 6) * kp, btnTex.w / 2 * sc, -0.012, 1, btnTex.h / 2 * sc);
    // mini meter: four bars, bouncing with the music in reactive mode, breathing slowly in ambient
    const bw = 6, gap = 3, x0 = r.x + 14 + 6, y0 = r.y + 13 + 34;
    for (let i = 0; i < 4; i++) {
      const v = reactive ? Math.min(1, [lv.b, (lv.b + lv.m) / 2, lv.m, lv.h * 1.5][i] * 1.1 + (fx.beatGlow || 0) * 0.25)
                         : 0.25 + 0.2 * Math.sin(S.time * 1.1 + i * 0.9);
      const hgt = Math.max(3, v * 28);
      drawRect((x0 + i * (bw + gap)) * kp, (y0 - hgt) * kp, bw * kp, hgt * kp, reactive ? [0.71, 1, 0.18] : [0.73, 0.64, 1], 1);
    }
    gl.disable(gl.BLEND);
  }

  // ---- clock HUD: the pink meter follows the music, the barcode scans each bar, the squares count beats ----
  if (overlay.hud && settings.clock) {
    const h = overlay.hud;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(P.card.p);
    gl.uniform2f(P.card.u.uRes, S.W, S.H);
    const level = Math.min(1, amb ? 0.25 + 0.15 * Math.sin(S.time * 1.3) : lv.b * 0.75 + lv.m * 0.35 + (fx.beatGlow || 0) * 0.25);
    S.meter = (S.meter || 0) + (level - (S.meter || 0)) * (1 - Math.exp(-dt * (level > (S.meter || 0) ? 30 : 6)));
    const lit = Math.round(S.meter * h.meter.segs);
    for (let i = 0; i < lit; i++) {
      const yy = h.meter.y + (h.meter.segs - 1 - i) * (h.meter.segH + h.meter.gap);
      drawRect(h.meter.x, yy, h.meter.w, h.meter.segH, i >= h.meter.segs - 2 ? [0.71, 1, 0.18] : [1, 1, 1], 0.95);
    }
    const c = music.clock;
    const per = c ? c.period : 500;
    const live = c && c.locked && !calm;
    const phase = live ? 1 - Math.max(0, Math.min(1, (c.next - Date.now()) / per)) : (S.time % 2) / 2;
    const pos = live ? (c.pos + 3) % 4 : Math.floor(S.time) % 4;
    const barFrac = (pos + phase) / 4;
    drawRect(h.barcode.x - 3 * kp, h.barcode.y + barFrac * h.barcode.h, h.barcode.w + 6 * kp, 3 * kp, [0.71, 1, 0.18], 1);
    for (let j = 0; j < 4; j++) if (j <= pos) drawRect(h.squares.x + j * h.squares.step, h.squares.y, h.squares.s, h.squares.s, j === pos ? [1, 0.17, 0.84] : [1, 1, 1], j === pos ? 1 : 0.85);
    drawRect(h.line.x, h.line.y, h.line.w * barFrac, 4 * kp, [0.71, 1, 0.18], 1);
    const secs = (now() % 60000) / 60000;
    drawRect(h.line.x, h.line.y + 8 * kp, h.line.w * secs, 2 * kp, [1, 0.17, 0.84], 0.9);
    gl.disable(gl.BLEND);
  }

  // ---- album cover above the now-playing block ----
  if (S.cover && overlay.np) {
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(P.card.p);
    const u2 = P.card.u, unit = kp * S.layout.k;
    const size = 250 * unit, half = size / 2;
    const np = overlay.np;
    const appear = Math.min(1, (S.time - S.cover.t0) / 0.5);
    const bump = (fx.bounce || 0) * 0.04;
    const cx = np.left ? np.right + half + 6 * unit : np.right - half - 6 * unit;
    const cy = np.top - 26 * unit - half;
    gl.uniform2f(u2.uRes, S.W, S.H);
    gl.uniform2f(u2.uCenter, cx, cy);
    gl.uniform2f(u2.uHalf, half, half);
    gl.uniform1f(u2.uPad, 70 * unit);
    gl.uniform1f(u2.uRot, -0.06 + Math.sin(S.time * 0.4) * 0.015);
    gl.uniform1f(u2.uScale, (0.85 + 0.15 * appear) * (1 + bump));
    gl.uniform1f(u2.uUnit, unit);
    gl.uniform1i(u2.uMode, M.STICKER | M.PLATES);
    gl.uniform1f(u2.uSeed, 3);
    bindTex(gl, 0, S.cover.tex); gl.uniform1i(u2.uTex, 0);
    gl.uniform4fv(u2.uCrop, S.cover.aspect > 1 ? [(1 - 1 / S.cover.aspect) / 2, 0, 1 / S.cover.aspect, 1] : [0, (1 - S.cover.aspect) / 2, 1, S.cover.aspect]);
    gl.uniform1f(u2.uSwap, 0);
    gl.uniform1f(u2.uFoil, 0.25);
    gl.uniform2f(u2.uLight, Math.sin(S.time * 0.7) * half, -half * 0.5);
    gl.uniform1f(u2.uAlpha, appear);
    gl.uniform1f(u2.uShadow, 1);
    gl.uniform1f(u2.uDim, 1);
    gl.uniform1f(u2.uLift, 0.4);
    gl.uniform1f(u2.uTime, S.time);
    drawQuad(gl);
    gl.disable(gl.BLEND);
  }

  // ---- stamps on top ----
  if (S.stamps.length) {
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(P.card.p);
    gl.uniform2f(P.card.u.uRes, S.W, S.H);
    S.stamps = S.stamps.filter(s => S.time - s.t0 < 0.9);
    for (const s of S.stamps) {
      const a = (S.time - s.t0) / 0.9;
      const pop = a < 0.12 ? 0.6 + a / 0.12 * 0.55 : 1.15 - Math.min(0.15, (a - 0.12) * 0.5);
      drawSprite(s.tex, s.x * kp, s.y * kp, 150 * kp * S.layout.k * s.scale * pop, s.rot, a < 0.7 ? 1 : 1 - (a - 0.7) / 0.3);
    }
    gl.disable(gl.BLEND);
  }
  S.frames = (S.frames || 0) + 1;
}

// ---------------------------------------------------------------- boot
async function boot() {
  applyGamut();
  const [pins, shelf] = await Promise.all([
    fetch('pins/manifest.json').then(r => r.json()),
    fetch('shelf.json').then(r => r.json()).catch(() => ({})),
  ]);
  S.pins = Array.isArray(pins) ? pins : [];
  S.empty = S.pins.length === 0;
  S.shelfCfg = shelf;
  try { await Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 2500))]); } catch (e) {}
  while (!S.area) { resize(); if (!S.area) await new Promise(r => setTimeout(r, 250)); }
  const tmpl = Q.has('tmpl') ? +Q.get('tmpl') : undefined;
  const l = makeLayout(S.pins, S.area, layoutOpts({ template: tmpl }));
  l.tmplIndex = tmpl;
  await texs.ensure(layoutPins(l), 6000);
  adopt(l);
  if (Q.has('track')) S.title = { text: Q.get('track'), artist: Q.get('artist') || '', t0: Date.now() - (+Q.get('tt') || 0) * 1000,
    chips: [acc.hot, acc.pop, acc.cool, acc.deep, acc.tape] };
  if (Q.has('cover')) fetch('pins/' + Q.get('cover')).then(r => r.blob()).then(b => new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(b); })).then(d => onTrack({ Title: Q.get('track') || 'Test', Artist: Q.get('artist') || '', Thumbnail: d }));
  if (Q.get('fx') === 'beat') { S.fx.punch = 0.03; S.fx.split = 6; S.fx.glitch = 0.9; S.fx.gseed = 7; }
  if (Q.has('stamp')) { const [x, y] = Q.get('stamp').split(',').map(Number); addStamp(x, y, 'ドン', 1); S.stamps[0].t0 = -0.3; S.fx.ring = { x, y, t0: -0.15 }; }
  S.last = performance.now();
  requestAnimationFrame(frame);
  setTimeout(prepNext, 3000);
  if (TEST) {
    // headless stills: freeze transient effects at the requested moment
    const hold = () => {
      if (Q.get('fx') === 'shatter' && S.frames === 4) { freeze(); adopt(makeLayout(S.pins, S.area, layoutOpts({ template: (+Q.get('tmpl') || 0) + 2 }))); }
      if (Q.get('fx') === 'shatter' && S.frames > 4) { S.fx.shatter = +Q.get('ft') || 0.3; S.fx.flash = 0.5; S.fx.speed = 0.8; }
      if (Q.get('fx') === 'beat') { S.fx.punch = 0.03; S.fx.split = 6; S.fx.glitch = 0.9; }
      if (Q.has('stamp')) { S.stamps.forEach(s => s.t0 = S.time - 0.3); if (S.fx.ring) S.fx.ring.t0 = S.time - 0.15; }
      requestAnimationFrame(hold);
    };
    hold();
  }
}

window.__pw = {
  S, music, beat: (pos = 0, accent = 1, down = true) => music.emit('beat', { pos, accent, down, period: 460 }),
  drop: () => music.emit('drop', {}), click, relayout, swapCard, onTrack,
  // test: save the current frame (plus the pasted icon row, if shown) to test/<name> via tools/serve.py
  async snap(name) {
    const c = document.createElement('canvas');
    c.width = canvas.width; c.height = canvas.height;
    const g = c.getContext('2d');
    g.drawImage(canvas, 0, 0);
    const ic = document.getElementById('icons');
    if (ic && ic.style.display === 'block' && ic.complete) g.drawImage(ic, 0, 0, ic.naturalWidth * S.dpr, ic.naturalHeight * S.dpr);
    const blob = await new Promise(r => c.toBlob(r, 'image/png'));
    await fetch('/save?name=' + encodeURIComponent(name), { method: 'POST', body: blob });
    return name;
  },
};
// report to the listener's log now and then (lets checks confirm mouse input and frame rate)
setInterval(() => {
  if (!music.connected) return;
  const f = S.frames || 0;
  music.ws.send(JSON.stringify({ type: 'stat', w: innerWidth, h: innerHeight, moves: S.moves || 0, hover: S.hover,
    fps: Math.round((f - (S.lastStatFrames || 0)) / 10), mode: music.mode, paused: S.paused,
    beats: S.beats, hits: S.hits || 0, connected: music.connected, clock: music.clock ? { locked: music.clock.locked, active: music.clock.active, bpm: music.clock.bpm, ahead: Math.round(music.clock.next - Date.now()) } : null,
    bounce: +(S.fx.bounce || 0).toFixed(2), gamut: (P3.matches ? 'p3' : 'srgb') + '/' + gl.drawingBufferColorSpace, err: (document.getElementById('err').textContent || '').slice(0, 300) }));
  S.lastStatFrames = f;
}, 10000);
boot();
