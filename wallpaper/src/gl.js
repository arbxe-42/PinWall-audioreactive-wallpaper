// Minimal WebGL2 helpers (copied from channel-surf/src/gl.js): programs, fullscreen triangle, render targets.

export const VERT = `#version 300 es
layout(location=0) in vec2 aPos;
out vec2 vUv;
void main() {
  vUv = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

// Shared GLSL snippets prepended to channel shaders.
export const COMMON = `
#define PI 3.14159265
#define TAU 6.28318531
float hash11(float p) { p = fract(p * .1031); p *= p + 33.33; p *= p + p; return fract(p); }
float hash21(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
vec2 hash22(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * vec3(.1031, .1030, .0973)); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.xx + p3.yz) * p3.zy); }
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash21(i), hash21(i + vec2(1, 0)), u.x), mix(hash21(i + vec2(0, 1)), hash21(i + vec2(1, 1)), u.x), u.y);
}
float fbm(vec2 p) {
  float s = 0.0, a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = m * p; a *= 0.5; }
  return s;
}
// iq cosine palette
vec3 pal(float t, vec3 a, vec3 b, vec3 c, vec3 d) { return a + b * cos(TAU * (c * t + d)); }
vec3 irid(float t) { return pal(t, vec3(.55), vec3(.45), vec3(1.0), vec3(0.0, .33, .67)); }
mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
`;

export function compile(gl, type, src) {
  const s = gl.createShader(type);
  gl.shaderSource(s, src);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(s);
    const numbered = src.split('\n').map((l, i) => `${i + 1}: ${l}`).join('\n');
    console.error(log + '\n' + numbered);
    throw new Error('Shader compile failed: ' + log);
  }
  return s;
}

export function program(gl, fragSrc, vertSrc = VERT) {
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vertSrc));
  gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fragSrc));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const uniforms = {};
  const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) {
    const info = gl.getActiveUniform(p, i);
    uniforms[info.name.replace(/\[0\]$/, '')] = gl.getUniformLocation(p, info.name);
  }
  return { p, u: uniforms };
}

let tri = null;
export function drawTri(gl) {
  if (!tri) {
    tri = gl.createVertexArray();
    gl.bindVertexArray(tri);
    const b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  }
  gl.bindVertexArray(tri);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
}

let floatOK = null;
export function canFloat(gl) {
  if (floatOK === null) floatOK = !!gl.getExtension('EXT_color_buffer_float');
  return floatOK;
}

// A render target. opts: { float, mips, linear, wrap }
export function target(gl, w, h, opts = {}) {
  const t = { w, h, opts, tex: gl.createTexture(), fb: gl.createFramebuffer() };
  allocate(gl, t, w, h);
  return t;
}

function allocate(gl, t, w, h) {
  const { float, mips, wrap } = t.opts;
  const useFloat = float && canFloat(gl);
  t.w = w; t.h = h;
  gl.bindTexture(gl.TEXTURE_2D, t.tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, useFloat ? gl.RGBA16F : gl.RGBA8, w, h, 0, gl.RGBA, useFloat ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE, null);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mips ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  const wm = wrap ? gl.REPEAT : gl.CLAMP_TO_EDGE;
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wm);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wm);
  if (mips) gl.generateMipmap(gl.TEXTURE_2D);
  gl.bindFramebuffer(gl.FRAMEBUFFER, t.fb);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, t.tex, 0);
  gl.clearColor(0, 0, 0, 1);
  gl.clear(gl.COLOR_BUFFER_BIT);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
}

export function resizeTarget(gl, t, w, h) {
  if (t.w === w && t.h === h) return false;
  allocate(gl, t, w, h);
  return true;
}

export function bindTarget(gl, t) {
  if (t) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, t.fb);
    gl.viewport(0, 0, t.w, t.h);
  } else {
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
  }
}

export function bindTex(gl, unit, tex) {
  gl.activeTexture(gl.TEXTURE0 + unit);
  gl.bindTexture(gl.TEXTURE_2D, tex);
}

// A 2D canvas that uploads into a GL texture (flipped so it matches GL's bottom-left origin).
export function canvasLayer(gl) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return {
    canvas, ctx, tex,
    size(w, h) {
      if (canvas.width === w && canvas.height === h) return false;
      canvas.width = w; canvas.height = h;
      return true;
    },
    upload() {
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    },
  };
}

let blitProg = null;
export function blit(gl, tex, dest) {
  if (!blitProg) {
    blitProg = program(gl, `#version 300 es
precision highp float;
in vec2 vUv; out vec4 o; uniform sampler2D uTex;
void main() { o = vec4(texture(uTex, vUv).rgb, 1.0); }`);
  }
  bindTarget(gl, dest);
  gl.useProgram(blitProg.p);
  bindTex(gl, 0, tex);
  gl.uniform1i(blitProg.u.uTex, 0);
  drawTri(gl);
}

// Ping-pong pair for feedback simulations.
export function pingpong(gl, w, h, opts) {
  const a = target(gl, w, h, opts), b = target(gl, w, h, opts);
  return {
    read: a, write: b,
    swap() { const t = this.read; this.read = this.write; this.write = t; },
    resize(w2, h2) { resizeTarget(gl, this.read, w2, h2); resizeTarget(gl, this.write, w2, h2); },
  };
}

// A unit quad (-1..1) for card-style draws.
let quadVao = null;
export function drawQuad(gl) {
  if (!quadVao) {
    quadVao = gl.createVertexArray();
    gl.bindVertexArray(quadVao);
    const b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  }
  gl.bindVertexArray(quadVao);
  gl.drawArrays(gl.TRIANGLES, 0, 6);
}
