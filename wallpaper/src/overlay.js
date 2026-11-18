// 2D overlay: the clock and date, the track title, and the stamp sprites.
// Text policy: only functional words (time, date, track) and graphic sound-effect stamps.
const DAYS = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

export function hex(c) { return '#' + c.map(v => Math.round(v).toString(16).padStart(2, '0')).join(''); }

export class Overlay {
  constructor(layer) { this.L = layer; this.key = ''; }

  // Returns true when the canvas changed (caller uploads it).
  draw(s) {
    const { W, H, k, area, corner, titleCorner, acc, showClock, now, title } = s;
    const d = new Date(now);
    const hh = String(d.getHours()).padStart(2, '0'), mm = String(d.getMinutes()).padStart(2, '0');
    const key = [W, H, corner, titleCorner, hh, mm, d.getSeconds(), s.bpm, s.empty, showClock, acc.map(hex).join(), title && title.text, title && (title.chips || []).length].join('|');
    if (key === this.key) return false;
    this.key = key;
    this.L.size(W, H);
    const g = this.L.ctx;
    g.clearRect(0, 0, W, H);
    const m = 46 * k;
    const left = corner[1] === 'l';
    const top = corner[0] === 't';

    this.hud = null;
    this.np = null;
    if (showClock) {
      // the sketch's clock cluster: big time, a pink level meter, a white barcode, a long info bar
      const fs = 230 * k;
      g.font = `${fs}px Anton, Impact, sans-serif`;
      g.textBaseline = 'alphabetic';
      const txt = `${hh}:${mm}`;
      const tw = g.measureText(txt).width;
      const x = left ? area.x + m : area.x + area.w - m - tw;
      const y = top ? area.y + m * 0.6 + fs * 0.86 : area.y + area.h - m - 64 * k;
      g.fillStyle = hex(acc[1]); g.fillText(txt, x + 7 * k, y);
      g.fillStyle = '#22e6ff'; g.fillText(txt, x - 7 * k, y);
      g.fillStyle = hex(acc[2]); g.fillText(txt, x, y);
      const capTop = y - fs * 0.73, capH = fs * 0.73;
      // pink meter block (the GL layer lights its segments with the music)
      const px = x + tw + 22 * k, pw = 66 * k;
      g.fillStyle = '#ff2bd6'; g.fillRect(px, capTop, pw, capH);
      g.fillStyle = 'rgba(0,0,0,0.28)';
      const segs = 12, gap = 4 * k, sh = (capH - 14 * k - gap * (segs - 1)) / segs;
      for (let i = 0; i < segs; i++) g.fillRect(px + 9 * k, capTop + 7 * k + i * (sh + gap), pw - 18 * k, sh);
      // white barcode
      const bx = px + pw + 14 * k, bw = 50 * k, bh = capH * 0.72;
      let sx = bx, i = 0;
      g.fillStyle = '#ffffff';
      while (sx < bx + bw) { const w = [3, 6, 2, 9, 3, 4, 2][i % 7] * k * 0.7; g.fillRect(sx, capTop, w, bh); sx += w + [3, 2, 5, 2, 4][i % 5] * k * 0.7; i++; }
      // four beat squares under the barcode
      const sq = 10 * k, sqy = capTop + bh + 14 * k;
      g.strokeStyle = '#ffffff'; g.lineWidth = 2 * k;
      for (let j = 0; j < 4; j++) g.strokeRect(bx + j * (sq + 3.3 * k), sqy, sq, sq);
      // the long bar underneath: date /// tempo /// seconds
      const right = bx + bw;
      const dy = y + 18 * k, dh = 44 * k;
      g.fillStyle = '#000'; g.fillRect(x, dy, right - x, dh);
      g.fillStyle = hex(acc[1]); g.fillRect(x, dy, 6 * k, dh);
      g.font = `700 ${24 * k}px "Space Mono", Consolas, monospace`;
      const parts = [`${DAYS[d.getDay()]} ${String(d.getDate()).padStart(2, '0')} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
        s.bpm ? `${Math.round(s.bpm)} BPM` : '--- BPM', `${hh}:${mm}:${String(d.getSeconds()).padStart(2, '0')}`];
      let tx = x + 18 * k;
      parts.forEach((t, j) => {
        if (j) { g.fillStyle = '#ff2bd6'; g.fillText('///', tx, dy + 31 * k); tx += g.measureText('/// ').width; }
        g.fillStyle = '#fff'; g.fillText(t, tx, dy + 31 * k); tx += g.measureText(t + ' ').width;
      });
      this.hud = { meter: { x: px + 9 * k, y: capTop + 7 * k, w: pw - 18 * k, segH: sh, gap, segs },
        barcode: { x: bx, y: capTop, w: bw, h: bh }, squares: { x: bx, y: sqy, s: sq, step: sq + 3.3 * k },
        line: { x, y: dy + dh + 6 * k, w: right - x } };
    }

    // border: crop marks in the corners, registration marks on the edges, ruler ticks down the sides
    {
      const L = area.x + 14 * k, R = area.x + area.w - 14 * k, T = area.y + 14 * k, B = area.y + area.h - 10 * k;
      g.strokeStyle = 'rgba(255,255,255,0.85)'; g.lineWidth = 3 * k;
      const arm = 44 * k;
      for (const [cx, cy, sx2, sy2] of [[L, T, 1, 1], [R, T, -1, 1], [L, B, 1, -1], [R, B, -1, -1]]) {
        g.beginPath(); g.moveTo(cx, cy + sy2 * arm); g.lineTo(cx, cy); g.lineTo(cx + sx2 * arm, cy); g.stroke();
      }
      g.strokeStyle = hex(acc[2]); g.lineWidth = 1.5 * k; g.globalAlpha = 0.55;
      g.strokeRect(L + 10 * k, T + 10 * k, R - L - 20 * k, B - T - 20 * k);
      g.globalAlpha = 1;
      const reg = (cx, cy) => {
        g.strokeStyle = '#fff'; g.lineWidth = 2 * k;
        g.beginPath(); g.arc(cx, cy, 9 * k, 0, Math.PI * 2); g.stroke();
        g.beginPath(); g.moveTo(cx - 16 * k, cy); g.lineTo(cx + 16 * k, cy); g.moveTo(cx, cy - 16 * k); g.lineTo(cx, cy + 16 * k); g.stroke();
      };
      reg((L + R) / 2, B); reg(L, (T + B) / 2); reg(R, (T + B) / 2);
      g.fillStyle = 'rgba(255,255,255,0.55)';
      for (let yy = T + 60 * k, n = 0; yy < B - 60 * k; yy += 24 * k, n++) {
        const len = n % 5 === 0 ? 16 * k : 7 * k;
        g.fillRect(L - 2 * k, yy, len, 2 * k);
        g.fillRect(R + 2 * k - len, yy, len, 2 * k);
      }
    }

    if (s.empty) {
      // nothing imported yet: say how to add images (functional text only)
      const cx = area.x + area.w / 2, cy = area.y + area.h / 2;
      g.textAlign = 'center';
      g.font = `${120 * k}px Anton, Impact, sans-serif`;
      g.fillStyle = '#ff2bd6'; g.fillText('ADD YOUR IMAGES', cx + 6 * k, cy + 6 * k);
      g.fillStyle = '#ffffff'; g.fillText('ADD YOUR IMAGES', cx, cy);
      g.font = `700 ${26 * k}px "Space Mono", Consolas, monospace`;
      g.fillStyle = '#b6ff2e';
      g.fillText('right-click the Pin Wall icon in the tray  >  Change images...', cx, cy + 70 * k);
      g.textAlign = 'left';
    }

    if (title && title.text) {
      // the sketch's now-playing block: lime tag, big title, artist strip, colour chips; it stays
      const tl = titleCorner[1] === 'l', tt = titleCorner[0] === 't';
      const chips = title.chips || [];
      const maxw = area.w * 0.34;
      let fs = 92 * k;
      g.font = `${fs}px Anton, Impact, sans-serif`;
      let lines = wrap(g, title.text.toUpperCase(), maxw);
      while (lines.length > 2 && fs > 52 * k) { fs -= 6 * k; g.font = `${fs}px Anton, Impact, sans-serif`; lines = wrap(g, title.text.toUpperCase(), maxw); }
      lines = lines.slice(0, 2);
      const lh = fs * 0.92;
      const blockH = 34 * k + 12 * k + lines.length * lh + 18 * k + 40 * k + 14 * k + 22 * k;
      let y = tt ? area.y + m : area.y + area.h - m * 0.7 - blockH;
      const rx = area.x + area.w - m;           // right edge (left edge if tl)
      const lx = area.x + m;
      const place = w => tl ? lx : rx - w;
      this.np = { right: tl ? lx : rx, top: y, left: tl };
      // tag
      g.font = `700 ${21 * k}px "Space Mono", Consolas, monospace`;
      const tag = 'NOW PLAYING';
      const tw = g.measureText(tag).width + 24 * k;
      g.fillStyle = hex(acc[2]); g.fillRect(place(tw), y, tw, 34 * k);
      g.fillStyle = '#000'; g.fillText(tag, place(tw) + 12 * k, y + 24 * k);
      y += 34 * k + 12 * k + fs * 0.86;
      // title lines
      g.font = `${fs}px Anton, Impact, sans-serif`;
      for (const l of lines) {
        const w = g.measureText(l).width;
        g.fillStyle = hex(acc[3] || acc[0]); g.fillText(l, place(w) + 6 * k, y + 6 * k);
        g.fillStyle = '#fff'; g.fillText(l, place(w), y);
        y += lh;
      }
      y += 18 * k - lh + fs * 0.14;
      // artist
      g.font = `700 ${23 * k}px "Space Mono", Consolas, monospace`;
      const ar = (title.artist || '').toUpperCase();
      if (ar) {
        const aw = g.measureText(ar).width + 24 * k;
        g.fillStyle = '#000'; g.fillRect(place(aw), y, aw, 40 * k);
        g.fillStyle = hex(acc[0]); g.fillRect(tl ? place(aw) : place(aw) + aw - 6 * k, y, 6 * k, 40 * k);
        g.fillStyle = '#fff'; g.fillText(ar, place(aw) + 12 * k, y + 28 * k);
      }
      y += 40 * k + 14 * k;
      const cw = chips.length * 52 * k;
      chipsRow(g, chips, place(cw), y, k);
    }
    return true;
  }
}

function chipsRow(g, chips, x, y, k) {
  chips.forEach((c, i) => { g.fillStyle = hex(c); g.fillRect(x + i * 52 * k, y, 46 * k, 22 * k); });
}

function wrap(g, text, maxw) {
  const words = text.split(/\s+/), lines = [];
  let cur = '';
  for (const w of words) {
    const t = cur ? cur + ' ' + w : w;
    if (g.measureText(t).width > maxw && cur) { lines.push(cur); cur = w; } else cur = t;
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 3);
}

// Stamp sprites: a yellow starburst with a manga sound effect (an art element, used sparingly).
export function makeStamp(text, fill = '#ffe14a') {
  const c = document.createElement('canvas');
  c.width = c.height = 512;
  const g = c.getContext('2d');
  const star = (dx, dy, col) => {
    g.save(); g.translate(256 + dx, 256 + dy); g.rotate(-0.14);
    g.beginPath();
    const n = 18;
    for (let i = 0; i < n * 2; i++) {
      const r = i % 2 ? 105 + (i * 37 % 40) : 230 - (i * 53 % 50);
      const a = (i / (n * 2)) * Math.PI * 2;
      g.lineTo(Math.cos(a) * r, Math.sin(a) * r);
    }
    g.closePath(); g.fillStyle = col; g.fill(); g.restore();
  };
  star(14, 14, '#000');
  star(0, 0, fill);
  if (text) {
    g.save(); g.translate(256, 262); g.rotate(-0.14);
    g.font = '900 150px "Noto Sans JP", "Yu Gothic", sans-serif';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.lineWidth = 10; g.strokeStyle = '#000'; g.strokeText(text, 0, 0);
    g.fillStyle = '#000'; g.fillText(text, 0, 0);
    g.restore();
  }
  return c;
}

// Huge outlined type for the background (the artist's name, or the day): drawn once per change.
export function makeBgText(text, px) {
  const c = document.createElement('canvas');
  const g = c.getContext('2d');
  const font = `${px}px Anton, Impact, sans-serif`;
  g.font = font;
  const t = text.toUpperCase() + '   ';
  const w = Math.min(16000, Math.ceil(g.measureText(t).width));
  c.width = w; c.height = Math.ceil(px * 1.05);
  g.font = font;
  g.textBaseline = 'alphabetic';
  g.lineJoin = 'round';
  g.lineWidth = Math.max(2, px * 0.009);
  g.strokeStyle = 'rgba(255,43,214,0.55)';
  g.strokeText(t, px * 0.012, px * 0.9 + px * 0.012);
  g.strokeStyle = 'rgba(182,255,46,0.9)';
  g.strokeText(t, 0, px * 0.9);
  return c;
}
