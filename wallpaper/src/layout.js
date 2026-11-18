// Composition templates and pin choice. Templates are designed on a 1920 x 1080 page (the sketch
// it grew from) and mapped onto the collage area below the icon shelf. Card sizes scale with the
// area's height, so pictures keep their shape on 16:9 and 16:10 screens alike.
import { M } from './shaders.js';

const T = (x, y, w, h, rot, mode, role = '') => ({ x, y, w, h, rot, mode, role });

// left/top/width/height on the 1920 x 1080 page
const BASE = {
  // A: the sketch. Hero centre-right, windows top right, clock top left.
  A: {
    clock: 'tl', title: 'br', dots: [0.22, 0.72],
    cards: [
      T(520, 110, 300, 400, -9, 'duo'),
      T(330, 300, 360, 270, 4, 'torn'),
      T(50, 420, 390, 520, -5, 'tape'),
      T(1640, 30, 250, 340, 5, ''),
      T(1290, 70, 440, 330, 2, 'win'),
      T(1040, 26, 280, 220, -3, 'win'),
      T(1430, 420, 370, 470, 6, 'tape'),
      T(640, 880, 560, 180, -1, 'torn'),
      T(420, 640, 300, 300, 0, 'circle'),
      T(1180, 690, 300, 300, -8, 'sticker'),
      T(1720, 760, 230, 230, -4, 'duo'),
      T(30, 860, 330, 240, 3, 'tape'),
      T(820, 150, 640, 780, -3, 'plates', 'hero'),
    ],
  },
  // C: hero left, a stack of windows and stickers on the right, clock top right.
  C: {
    clock: 'tr', title: 'bl', dots: [0.78, 0.7],
    cards: [
      T(760, 70, 270, 350, -7, 'duo'),
      T(1010, 430, 330, 430, -4, 'tape'),
      T(1000, 40, 450, 330, -2, 'win'),
      T(1690, 380, 210, 280, 8, 'duo'),
      T(1390, 310, 420, 320, 3, 'win'),
      T(560, 640, 360, 280, -3, 'torn'),
      T(860, 760, 280, 280, 6, 'sticker'),
      T(1560, 690, 290, 290, 0, 'circle'),
      T(1270, 790, 380, 250, 2, 'tape'),
      T(90, 880, 620, 170, 1, 'torn'),
      T(1440, 40, 230, 250, -6, ''),
      T(190, 150, 600, 760, 3, 'plates', 'hero'),
    ],
  },
  // D: two big pictures crossing, small stuff in the corners, clock bottom left.
  D: {
    clock: 'bl', title: 'tr', dots: [0.5, 0.5],
    cards: [
      T(60, 60, 330, 250, -4, 'win'),
      T(1500, 600, 380, 280, 3, 'torn'),
      T(1620, 180, 240, 330, 7, 'duo'),
      T(80, 360, 300, 300, 0, 'circle'),
      T(1340, 860, 420, 180, -2, 'torn'),
      T(420, 40, 260, 260, -9, 'sticker'),
      T(1250, 60, 330, 250, 5, 'tape'),
      T(1190, 330, 520, 640, 4, 'plates', 'hero2'),
      T(560, 180, 600, 740, -4, 'plates', 'hero'),
    ],
  },
};

function mirror(t) {
  const flip = { tl: 'tr', tr: 'tl', bl: 'br', br: 'bl' };
  return {
    clock: flip[t.clock], title: flip[t.title], dots: [1 - t.dots[0], t.dots[1]],
    cards: t.cards.map(c => ({ ...c, x: 1920 - c.x - c.w, rot: -c.rot })),
  };
}

export const TEMPLATES = [BASE.A, mirror(BASE.A), BASE.C, mirror(BASE.C), BASE.D, mirror(BASE.D)];

const MODE_BITS = { duo: M.DUO, torn: M.TORN, circle: M.CIRCLE, sticker: M.STICKER, win: M.WINDOW, plates: M.PLATES, tape: 0, '': 0 };

export function rng(seed) {
  let s = (seed >>> 0) || 1;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

function colDist(a, b) {
  const dr = a[0] - b[0], dg = a[1] - b[1], db = a[2] - b[2];
  return Math.sqrt(2 * dr * dr + 4 * dg * dg + 3 * db * db);
}

// How well a pin's palette matches a target palette (0 = perfect). target: [[r,g,b], ...]
export function paletteScore(pin, target) {
  if (!target || !target.length) return 0;
  let s = 0;
  for (const [r, g, b, w] of pin.palette.slice(0, 3)) {
    let best = 1e9;
    for (const t of target) best = Math.min(best, colDist([r, g, b], t));
    s += best * w;
  }
  return s / 255;
}

// Score a pin for a slot: shape fit, colour, quality, freshness. Lower is better.
function pinCost(pin, slot, opts, r) {
  const a = slot.w / slot.h;
  let cost = Math.abs(Math.log(pin.aspect / a)) * 2.2;
  if (slot.role.startsWith('hero')) {
    cost += pin.anim ? 3 : 0;
    cost += Math.max(0, 900 - Math.max(pin.w, pin.h)) / 300;
    cost += (0.45 - Math.min(0.45, pin.sat)) * 3;
    cost += Math.max(0, 0.34 - pin.lum) * 9;          // a hero must not be a mostly black picture
  }
  if (slot.mode === 'duo') cost -= 0.3 * (1 - pin.sat);   // two-tone suits busy, greyish pictures
  if (pin.family === 'ink') cost += 0.8;                   // colour and light first, ink only a flavour
  if (opts.palette) cost += paletteScore(pin, opts.palette) * 2.5;
  if (opts.recent && opts.recent.has(pin.id)) cost += 2.0;
  return cost + r() * 1.2;
}

export function choosePin(pins, slot, used, opts, r) {
  let best = null, bc = 1e9;
  for (const p of pins) {
    if (used.has(p.id)) continue;
    const c = pinCost(p, slot, opts, r);
    if (c < bc) { bc = c; best = p; }
  }
  return best;
}

// Cover-fit crop of a pin into a slot shape; portraits keep their upper part (faces).
export function cropFor(pin, w, h) {
  const a = w / h, pa = pin.aspect;
  if (pa > a) { const cw = a / pa; return [(1 - cw) / 2, 0, cw, 1]; }
  const ch = pa / a; return [0, (1 - ch) * 0.3, 1, ch];
}

// Build a layout for an area { x, y, w, h } (css px).
export function makeLayout(pins, area, opts = {}) {
  const r = rng(opts.seed ?? 1);
  // the first composition reads best (clock top left, now playing bottom right): always A,
  // with fresh pictures, jitter and a different back layer each time
  const tmpl = TEMPLATES[(opts.template ?? 0) % TEMPLATES.length];
  const k = area.h / 1080;                       // scale for sizes
  const sx = area.w / 1920, sy = area.h / 1080;  // scale for positions
  const used = new Set();
  const cards = [];
  // heroes first so they get the best pictures
  const order = [...tmpl.cards.keys()].sort((i, j) => (tmpl.cards[j].role ? 1 : 0) - (tmpl.cards[i].role ? 1 : 0));
  const placed = [];
  for (const i of order) {
    const s = tmpl.cards[i];
    const w = s.w * k, h = s.h * k;
    const cx = area.x + (s.x + s.w / 2) * sx + (r() - 0.5) * 30 * k;
    const cy = area.y + (s.y + s.h / 2) * sy + (r() - 0.5) * 24 * k;
    const pin = choosePin(pins, s, used, opts, r);
    if (!pin) continue;
    used.add(pin.id);
    placed[i] = {
      pin, cx, cy, w, h, rot: (s.rot + (r() - 0.5) * 3) * Math.PI / 180,
      mode: MODE_BITS[s.mode] | 0, kind: s.mode, role: s.role,
      tape: s.mode === 'tape', depth: s.role ? 0.55 : 0.25 + r() * 0.7,
      crop: s.mode === 'win' ? cropFor(pin, w - 8 * k, h - 40 * k) : cropFor(pin, w, h),
      seed: r() * 100,
    };
  }
  for (const c of placed) if (c) cards.push(c);

  // back layer: a scatter of smaller, dimmer pictures filling every gap behind the collage
  const back = [];
  const cols = 6, rows = 3;
  for (let gy = 0; gy < rows; gy++) {
    for (let gx = 0; gx < cols; gx++) {
      if (r() < 0.18) continue;
      const bw = (190 + r() * 150) * k;
      const pin = choosePin(pins, { w: bw, h: bw * (0.75 + r() * 0.6), mode: '', role: '' }, used, opts, r);
      if (!pin) continue;
      used.add(pin.id);
      const bh = Math.min(bw / pin.aspect, bw * 1.5);
      const modes = ['', '', 'duo', 'torn'];
      const kind = modes[Math.floor(r() * modes.length)];
      back.push({
        pin, w: bw, h: bh,
        cx: area.x + ((gx + 0.5 + (r() - 0.5) * 0.8) / cols) * area.w,
        cy: area.y + ((gy + 0.5 + (r() - 0.5) * 0.8) / rows) * area.h,
        rot: (r() - 0.5) * 28 * Math.PI / 180, mode: MODE_BITS[kind] | 0, kind, role: '', tape: false,
        depth: 0.06 + r() * 0.12, crop: cropFor(pin, bw, bh), seed: r() * 100, back: true,
      });
    }
  }
  // print marks: sparkles, registration marks, small bursts, barcodes
  const marks = [];
  const kinds = ['spark', 'spark', 'spark', 'reg', 'burst', 'barcode', 'plus'];
  for (let i = 0; i < 26; i++) {
    marks.push({
      kind: kinds[Math.floor(r() * kinds.length)],
      x: area.x + r() * area.w, y: area.y + r() * area.h,
      size: (14 + r() * 26) * k, rot: (r() - 0.5) * 0.8, phase: r() * 6.28, depth: 0.1 + r() * 0.5,
    });
  }
  return { cards, back, marks, clock: tmpl.clock, title: tmpl.title, dots: tmpl.dots, k, area };
}
