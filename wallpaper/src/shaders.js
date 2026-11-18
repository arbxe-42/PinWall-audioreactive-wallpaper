// All GLSL for Pin Wall. Pixel coordinates are y-down (top-left origin) everywhere except
// where a fullscreen pass reads vUv (y-up), which it converts first.
import { COMMON } from './gl.js';

export const CARD_VERT = `#version 300 es
layout(location=0) in vec2 aPos;
uniform vec2 uRes;      // target size, px
uniform vec2 uCenter;   // card centre, px
uniform vec2 uHalf;     // card half size, px
uniform float uPad;     // extra px around the card (shadow, print plates, rings)
uniform float uRot;     // radians
uniform float uScale;
out vec2 vP;            // px from the card centre, in the card's own (unrotated) frame
void main() {
  vec2 p = aPos * (uHalf + uPad);
  vP = p;
  float c = cos(uRot), s = sin(uRot);
  vec2 w = vec2(c * p.x - s * p.y, s * p.x + c * p.y) * uScale + uCenter;
  gl_Position = vec4(w.x / uRes.x * 2.0 - 1.0, 1.0 - w.y / uRes.y * 2.0, 0.0, 1.0);
}`;

// Modes (bit flags)
export const M = { PLATES: 1, DUO: 2, TORN: 4, CIRCLE: 8, STICKER: 16, WINDOW: 32, TAPE: 64, SPRITE: 128, PLAIN: 256 };

export const CARD_FRAG = `#version 300 es
precision highp float;
${COMMON}
in vec2 vP;
out vec4 o;
uniform sampler2D uTex, uTexB;
uniform vec2 uHalf;
uniform float uUnit;          // px per layout unit (1 css px)
uniform vec4 uCrop, uCropB;   // x0, y0, w, h in texture uv (v = 0 at the image top)
uniform int uMode;
uniform float uSeed, uTime;
uniform vec3 uAcc1, uAcc2, uAcc3, uInk, uRingCol;
uniform float uSwap;          // 0..1 transition from uTex to uTexB
uniform int uSwapKind;        // 0 datamosh smear, 1 rip along uSwapDir
uniform vec2 uSwapDir;
uniform float uFoil;          // 0..1 holo foil (hover)
uniform vec2 uLight;          // foil light position, card px
uniform float uAlpha, uShadow, uLift, uShimmer, uDim;
uniform vec4 uTint;           // rgb tint + amount (sprites)

float sdBox(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }

vec3 sampleImg(sampler2D t, vec4 crop, vec2 uv) {
  return texture(t, crop.xy + clamp(uv, 0.0, 1.0) * crop.zw).rgb;
}

// The card's picture, with the swap transition applied.
vec3 picture(vec2 uv, vec2 p) {
  vec3 a = sampleImg(uTex, uCrop, uv);
  if (uSwap <= 0.0) return a;
  if (uSwap >= 1.0) return sampleImg(uTexB, uCropB, uv);
  if (uSwapKind == 1) {
    // rip: a torn line sweeps across along the drag direction
    vec2 d = normalize(uSwapDir + 1e-4);
    float L = dot(abs(d), uHalf) + 30.0;
    float line = dot(p, d) + (fbm(p * 0.04 + uSeed) - 0.5) * 60.0 + (vnoise(p * 0.3) - 0.5) * 8.0;
    float edge = mix(-L, L, uSwap);
    vec3 b = sampleImg(uTexB, uCropB, uv);
    if (line < edge - 4.0) return b;
    if (line < edge) return vec3(0.95, 0.93, 0.88);     // the torn paper fibres
    return a * (1.0 - 0.35 * smoothstep(edge + 30.0, edge, line)); // shadow under the flap
  }
  // datamosh smear: blocks flip to the new picture; the old one smears sideways first
  vec2 bs = vec2(28.0, 14.0) * uUnit;
  vec2 cell = floor(p / bs);
  float r = hash21(cell + uSeed * 13.1);
  float row = hash11(cell.y * 7.3 + uSeed);
  float pr = uSwap * 1.25 - 0.12;
  float s = sin(PI * uSwap);
  if (r < pr - 0.15) {
    vec2 uvb = uv + vec2((row - 0.5) * 0.12 * s, 0.0);
    return sampleImg(uTexB, uCropB, uvb);
  }
  vec2 uva = uv;
  uva.x += (row - 0.5) * 0.45 * s * step(0.55, hash11(cell.y + uSeed * 3.0));
  uva.y = mix(uva.y, floor(uva.y * 24.0) / 24.0, s * 0.8);
  vec3 c = sampleImg(uTex, uCrop, uva);
  if (r < pr) c = mix(c, sampleImg(uTexB, uCropB, uv).gbr, 0.6);   // the hot edge of the flip
  return c;
}

void main() {
  vec2 p = vP;
  vec2 h = uHalf;
  vec4 col = vec4(0.0);

  if ((uMode & ${M.SPRITE}) != 0) {
    vec2 uv = p / h * 0.5 + 0.5;
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) discard;
    vec4 t = texture(uTex, uv);
    t.rgb = mix(t.rgb, uTint.rgb, uTint.a * t.a);
    o = vec4(t.rgb, t.a * uAlpha);
    return;
  }

  if ((uMode & ${M.PLAIN}) != 0) {           // solid rectangle (HUD bits)
    if (abs(p.x) > h.x || abs(p.y) > h.y) discard;
    o = vec4(uTint.rgb, uAlpha);
    return;
  }

  if ((uMode & ${M.TAPE}) != 0) {
    float d = sdBox(p, h, 0.0);
    float jag = (hash11(floor(p.y / (3.0 * uUnit)) + uSeed) - 0.5) * 6.0 * uUnit;
    float dx = abs(p.x) - h.x + jag;
    if (d > 0.0 || dx > 0.0) discard;
    float grain = vnoise(p * 0.35) * 0.08;
    o = vec4(uAcc3 * (0.92 + grain), 0.72 * uAlpha);
    return;
  }

  // ---- card shape (signed distance, px) ----
  bool circle = (uMode & ${M.CIRCLE}) != 0;
  bool sticker = (uMode & ${M.STICKER}) != 0;
  bool torn = (uMode & ${M.TORN}) != 0;
  bool win = (uMode & ${M.WINDOW}) != 0;
  float radius = sticker ? 26.0 * uUnit : 1.5 * uUnit;
  float R = min(h.x, h.y);
  float d = circle ? length(p) - R : sdBox(p, h, radius);
  if (torn) d += (fbm(p * 0.03 / uUnit + uSeed) - 0.5) * 16.0 * uUnit + (vnoise(p * 0.45 / uUnit) - 0.5) * 3.0 * uUnit;

  // ---- drop shadow (lies on the cards below) ----
  vec2 so = vec2(0.0, 16.0 + 30.0 * uLift) * uUnit;
  float sd = circle ? length(p - so) - R : sdBox(p - so, h, radius);
  float blur = (22.0 + 26.0 * uLift) * uUnit;
  float sh = (1.0 - smoothstep(-blur, blur, sd)) * (0.62 + 0.2 * uLift) * uShadow;
  col = vec4(0.0, 0.0, 0.0, sh);

  // ---- print plates out of register ----
  if ((uMode & ${M.PLATES}) != 0) {
    vec2 off = vec2(7.0, 0.0) * uUnit;
    float dm = sdBox(p - off, h, radius), dc = sdBox(p + off, h, radius);
    if (dc < 0.0) col = vec4(mix(col.rgb, vec3(0.13, 0.9, 1.0) * 0.95, 0.9), max(col.a, 0.9));
    if (dm < 0.0) col = vec4(mix(col.rgb, vec3(1.0, 0.17, 0.84) * 0.95, 0.9), max(col.a, 0.9));
  }
  // ---- ring around circle cuts ----
  if (circle) {
    float ring = abs(length(p) - (R + 11.0 * uUnit)) - 3.0 * uUnit;
    if (ring < 0.0) col = vec4(uRingCol, 1.0);
  }

  if (d < 0.0) {
    vec2 inner = h;
    vec2 q = p;
    vec3 c;
    if (win) {
      float tb = 30.0 * uUnit, bw = 4.0 * uUnit;
      vec2 b0 = vec2(-h.x + bw, -h.y + bw + tb + 2.0 * uUnit), b1 = vec2(h.x - bw, h.y - bw);
      // bevelled grey frame
      c = vec3(0.753);
      float bev = 2.0 * uUnit;
      if (p.x < -h.x + bev || p.y < -h.y + bev) c = vec3(1.0);
      if (p.x > h.x - bev || p.y > h.y - bev) c = vec3(0.25);
      // title bar
      if (p.y > -h.y + bw && p.y < -h.y + bw + tb && p.x > -h.x + bw && p.x < h.x - bw) {
        float g = (p.x + h.x) / (2.0 * h.x);
        c = mix(vec3(0.04, 0.1, 0.54), vec3(0.06, 0.52, 0.82), g);
        // three buttons on the right
        for (int i = 0; i < 3; i++) {
          vec2 bc = vec2(h.x - bw - (14.0 + float(i) * 25.0) * uUnit, -h.y + bw + tb * 0.5);
          vec2 bp = p - bc;
          if (abs(bp.x) < 11.0 * uUnit && abs(bp.y) < 9.5 * uUnit) {
            c = vec3(0.753);
            if (bp.x < -9.5 * uUnit || bp.y < -8.0 * uUnit) c = vec3(1.0);
            if (bp.x > 9.5 * uUnit || bp.y > 8.0 * uUnit) c = vec3(0.25);
            float gly = i == 0 ? max(abs(bp.x + bp.y), abs(bp.x - bp.y)) - 1.2 * uUnit - 0.0 * uUnit
                      : (i == 1 ? abs(sdBox(bp, vec2(5.5, 4.5) * uUnit, 0.0)) - 0.8 * uUnit
                                : sdBox(bp - vec2(0.0, 4.0 * uUnit), vec2(5.0, 1.0) * uUnit, 0.0));
            if (i == 0) gly = max(gly, sdBox(bp, vec2(5.0) * uUnit, 0.0));
            if (gly < 0.0) c = vec3(0.0);
          }
        }
      }
      if (all(greaterThan(p, b0)) && all(lessThan(p, b1))) {
        vec2 uv = (p - b0) / (b1 - b0);
        c = picture(uv, p);
      }
    } else {
      float inset = sticker ? 10.0 * uUnit : 0.0;
      vec2 uv;
      if (circle) uv = p / (2.0 * R) + 0.5;
      else uv = (p / (h - inset)) * 0.5 + 0.5;
      c = picture(uv, p);
      if ((uMode & ${M.DUO}) != 0) {
        // two-tone print: deep ink to a pale tint of the accent, with a fine halftone in the shadows
        float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
        l = pow(smoothstep(0.04, 0.85, l), 0.85);
        vec3 light = mix(uAcc2, vec3(1.0), 0.45);
        vec3 duo = mix(uInk, light, l);
        vec2 cellp = mod(gl_FragCoord.xy, 7.0 * uUnit) - 3.5 * uUnit;
        float rr = (1.0 - l) * 2.9 * uUnit;
        float dotm = 1.0 - smoothstep(rr - 0.7, rr + 0.7, length(cellp));
        c = mix(duo, duo * mix(vec3(1.0), uAcc1, 0.9) * 0.8, dotm * 0.6 * (1.0 - l * 0.5));
      }
      if (sticker && sdBox(p, h - inset, max(radius - inset, 0.0)) > 0.0) c = vec3(0.97, 0.96, 0.94);
      if (torn && d > -3.5 * uUnit) c = mix(c, vec3(0.94, 0.91, 0.85), 0.85);   // torn paper rim
    }
    c = mix(vec3(dot(c, vec3(0.299, 0.587, 0.114))), c, 0.7 + 0.3 * uDim) * uDim;   // back layer: dimmer, a touch greyer
    // holo foil on hover: iridescent sheen + a moving glint band
    if (uFoil > 0.0) {
      vec2 n = p / h;
      vec2 L = uLight / h;
      float ang = dot(n - L, vec2(0.62, 0.38));
      vec3 ir = irid(ang * 0.9 + uTime * 0.04 + fbm(n * 3.0) * 0.4);
      float band = exp(-pow((n.x * 0.75 + n.y * 0.55 - (L.x * 0.75 + L.y * 0.55)) * 3.2, 2.0));
      vec3 lit = c * (0.75 + ir * 0.7) + band * 0.45 + ir * 0.12 * (1.0 + uShimmer);
      c = mix(c, lit, uFoil);
    }
    c += uShimmer * 0.05 * irid(p.x * 0.004 + uTime * 0.2) * float((uMode & ${M.PLATES}) != 0);
    float aa = 1.0 - smoothstep(-1.0, 0.5, d);
    col = vec4(mix(col.rgb, c, aa), max(col.a, aa));
  }
  if (col.a <= 0.002) discard;
  o = vec4(col.rgb, col.a * uAlpha);
}`;

export const BG_FRAG = `#version 300 es
precision highp float;
${COMMON}
in vec2 vUv; out vec4 o;
uniform vec2 uRes; uniform float uTime, uUnit, uHigh, uBass, uRayRot, uBeat;
uniform vec2 uCenter, uDots, uPar;
uniform vec3 uAcc1, uAcc2, uAcc3, uBase, uRingCol;
void main() {
  vec2 p = vec2(vUv.x, 1.0 - vUv.y) * uRes;
  vec3 c = uBase;
  vec2 q = p - (uCenter + uPar * 0.6);
  float a = atan(q.y, q.x);
  float rays = step(fract(a / TAU * 30.0 + uTime * 0.004 + uRayRot), 0.34);
  float fall = smoothstep(0.0, 260.0 * uUnit, length(q));
  c = mix(c, mix(c, uAcc1, 0.16 + 0.2 * uBass + 0.18 * uBeat), rays * fall);
  // concentric rings around the hero, breathing with the bass and kicking out on the beat
  float rr = length(q);
  for (int i = 0; i < 4; i++) {
    float R = (360.0 + float(i) * 120.0) * uUnit * (1.0 + 0.05 * uBass + 0.07 * uBeat * (1.0 + float(i) * 0.4));
    float ring = 1.0 - smoothstep(1.5 * uUnit, 3.2 * uUnit, abs(rr - R));
    c = mix(c, uRingCol, ring * (0.22 + 0.4 * uBeat) * (1.0 - float(i) * 0.18));
  }
  // halftone dot field, fading out from a corner
  vec2 dp = p + uPar * 0.3;
  vec2 cell = mod(dp, 14.0 * uUnit) - 7.0 * uUnit;
  float m = 1.0 - smoothstep(0.0, 0.55, length((p - uDots) / uRes * vec2(1.0, 1.3)));
  float r = (1.6 + 0.8 * uHigh) * uUnit;
  float dotm = 1.0 - smoothstep(r - 0.6, r + 0.6, length(cell));
  c = mix(c, uAcc2, dotm * m * 0.3);
  c += (hash21(p + fract(uTime) * 91.0) - 0.5) * 0.025;
  o = vec4(c, 1.0);
}`;

export const POST_FRAG = `#version 300 es
precision highp float;
${COMMON}
in vec2 vUv; out vec4 o;
uniform sampler2D uComp, uFrozen, uOver;
uniform vec2 uRes;
uniform float uTime, uUnit;
uniform float uPunch, uBreath, uSplit, uGlitch, uGlitchSeed;
uniform vec2 uShake;
uniform float uShatter;       // seconds since the shatter started (< 0: none)
uniform vec4 uShardA[26];     // shard seed (px), flight direction * speed (px/s)
uniform float uShardR[26];    // shard spin per second
uniform float uDissolve;      // 0..1 old (uFrozen) -> new (uComp); 1 = none
uniform float uFlash, uSpeed;
uniform vec4 uRing;           // x, y, radius, strength (px)
uniform float uShelfH, uPulse, uBottom;
uniform vec4 uPlates[6];      // x0, x1, glow, 0 (px)
uniform int uNPlates;
uniform vec2 uPlateY;         // y0, y1 of the plates (px)
uniform vec3 uAcc1, uAcc2, uAcc3, uBase;
uniform float uCalib;

vec3 comp(sampler2D t, vec2 px) { return texture(t, vec2(px.x / uRes.x, 1.0 - px.y / uRes.y)).rgb; }

float sdBox(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }

vec3 shelf(vec2 px) {
  vec3 c = uBase * 0.85;
  // quiet print texture: fine diagonal hatch and grain
  c += 0.012 * step(0.5, fract((px.x + px.y) / (6.0 * uUnit)));
  c += (hash21(px) - 0.5) * 0.015;
  for (int i = 0; i < 6; i++) {
    if (i >= uNPlates) break;
    vec4 pl = uPlates[i];
    vec2 ctr = vec2((pl.x + pl.y) * 0.5, (uPlateY.x + uPlateY.y) * 0.5);
    vec2 hb = vec2((pl.y - pl.x) * 0.5, (uPlateY.y - uPlateY.x) * 0.5);
    float d = sdBox(px - ctr, hb, 10.0 * uUnit);
    vec3 fill = mix(uBase, uAcc2, 0.10 + 0.10 * pl.z);
    fill += 0.03 * step(0.5, fract((px.x - px.y) / (5.0 * uUnit)));
    if (d < 0.0) c = fill;
    float line = abs(d) - (1.0 + 0.6 * pl.z) * uUnit;
    float glow = exp(-max(d, 0.0) / (10.0 * uUnit)) * pl.z * 0.35;
    c += uAcc1 * glow;
    if (line < 0.0) c = mix(c, uAcc1, 0.55 + 0.45 * max(pl.z, uPulse));
    // a strip of tape on the top-left corner
    vec2 tp = px - (ctr + vec2(-hb.x + 16.0 * uUnit, -hb.y + 2.0 * uUnit));
    tp = mat2(0.94, 0.34, -0.34, 0.94) * tp;
    if (abs(tp.x) < 24.0 * uUnit && abs(tp.y) < 6.0 * uUnit) c = mix(c, uAcc3, 0.7);
    if (uCalib > 0.5 && abs(d) < 2.0 * uUnit) c = vec3(1.0, 0.0, 0.0);
  }
  // the band's lower edge: a hairline and a soft shadow onto the collage
  return c;
}

void main() {
  vec2 px = vec2(vUv.x, 1.0 - vUv.y) * uRes;
  if (px.y < uShelfH) { o = vec4(shelf(px), 1.0); return; }

  vec2 ctr = vec2(uRes.x * 0.5, (uRes.y + uShelfH) * 0.5);
  vec2 q = ctr + (px - ctr) / (1.0 + uPunch + uBreath) - uShake;

  // shockwave ring from a click
  if (uRing.w > 0.0) {
    vec2 dv = px - uRing.xy;
    float dd = length(dv) - uRing.z;
    float k = exp(-dd * dd / (900.0 * uUnit * uUnit));
    q -= normalize(dv + 1e-4) * k * 18.0 * uUnit * uRing.w;
  }
  // glitch slices
  if (uGlitch > 0.0) {
    float band = floor(q.y / (uRes.y / 26.0));
    float r = hash11(band * 1.7 + uGlitchSeed);
    if (r < uGlitch * 0.45) q.x += (hash11(band * 3.1 + uGlitchSeed) - 0.5) * uGlitch * 160.0 * uUnit;
  }

  vec3 c;
  vec2 sp = vec2(uSplit, 0.0);
  c.r = comp(uComp, q + sp).r;
  c.g = comp(uComp, q).g;
  c.b = comp(uComp, q - sp).b;

  // soft dissolve from the old wall to the new one
  if (uDissolve < 1.0) {
    float n = fbm(px / (180.0 * uUnit) + 3.0) * 0.8 + hash21(floor(px / (6.0 * uUnit))) * 0.2;
    float m = smoothstep(n - 0.08, n + 0.08, uDissolve * 1.2 - 0.1);
    vec3 old = comp(uFrozen, q);
    c = mix(old, c, m);
  }

  // shatter: the frozen wall breaks into shards that fly out from the centre
  if (uShatter >= 0.0) {
    float t = uShatter;
    vec2 cen = ctr;
    float best = 1e9, second = 1e9; vec2 bestOff = vec2(0); float bestRot = 0.0; vec2 bestSeed = vec2(0); float bid = 0.0;
    // shard seeds, flight vectors and spins come precomputed from main.js (uShardA / uShardR): the
    // per-pixel loop only measures distances (it used to hash and normalise 26 times per pixel)
    for (int i = 0; i < 26; i++) {
      vec4 sa = uShardA[i];
      vec2 off = sa.zw * (t * 0.9 + 0.6 * t * t);
      float dd = length(px - (sa.xy + off));
      if (dd < best) { second = best; best = dd; bestOff = off; bestSeed = sa.xy; bid = float(i); }
      else if (dd < second) second = dd;
    }
    bestRot = uShardR[int(bid)] * t;
    vec2 src = bestSeed + rot(-bestRot) * (px - bestSeed - bestOff);
    vec3 sh = comp(uFrozen, src);
    if (mod(bid, 5.0) == 1.0) sh = 1.0 - sh;
    if (mod(bid, 4.0) == 2.0) sh = sh.gbr;
    float gap = second - best;
    float crack = smoothstep(2.0 * uUnit, 0.0, gap - t * 60.0 * uUnit);
    float vis = 1.0 - smoothstep(0.75, 1.35, t);
    float inShard = step(t * 70.0 * uUnit, gap);
    vec3 under = c * smoothstep(0.2, 1.0, t);
    c = mix(under, sh, inShard * vis);
    c = mix(c, vec3(1.0), crack * vis * (1.0 - smoothstep(0.0, 0.25, t)) * 0.9);
  }

  // speed lines and flash
  if (uSpeed > 0.0) {
    vec2 v = px - ctr;
    float a = atan(v.y, v.x);
    float lines = step(0.86, hash11(floor(a / TAU * 220.0)));
    float rm = smoothstep(220.0 * uUnit, 900.0 * uUnit, length(v));
    c = mix(c, vec3(1.0), lines * rm * uSpeed * 0.7);
  }
  if (uFlash > 0.0) {
    float r = length(px - ctr) / (uRes.y * 0.6);
    c = mix(c, vec3(1.0), uFlash * exp(-r * r * 2.5));
  }
  if (uRing.w > 0.0) {
    float dd = abs(length(px - uRing.xy) - uRing.z);
    c = mix(c, vec3(1.0), (1.0 - smoothstep(0.0, 4.0 * uUnit, dd)) * uRing.w * 0.7);
  }

  // text and stamps overlay (straight alpha)
  vec4 ov = texture(uOver, vUv);
  c = mix(c, ov.rgb, ov.a);

  // border: halftone dots creeping in from the edges of the collage
  {
    float de = min(min(px.x, uRes.x - px.x), min(px.y - uShelfH, uRes.y - uBottom - px.y));
    vec2 cell = mod(px, 11.0 * uUnit) - 5.5 * uUnit;
    float r = smoothstep(60.0 * uUnit, 0.0, de) * (3.2 + 1.2 * uPulse) * uUnit;
    float dotm = 1.0 - smoothstep(r - 0.7, r + 0.7, length(cell));
    c = mix(c, uAcc1, dotm * 0.6);
  }
  // shadow from the shelf band onto the collage
  if (uShelfH > 0.0) c *= 1.0 - 0.55 * exp(-(px.y - uShelfH) / (14.0 * uUnit));
  // vignette
  vec2 vv = vUv - 0.5;
  c *= 1.0 - 0.22 * dot(vv, vv) * 2.0;
  o = vec4(c, 1.0);
}`;
