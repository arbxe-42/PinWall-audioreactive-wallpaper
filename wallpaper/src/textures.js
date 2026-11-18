// Pin textures: loaded on demand, kept in a small LRU, animated GIFs decoded frame by frame.
export class PinTextures {
  constructor(gl, base = 'pins/', limit = 60) {
    this.gl = gl; this.base = base; this.limit = limit;
    this.map = new Map();   // id -> entry
    this.blank = this._solid([20, 12, 28, 255]);
  }

  _solid(rgba) {
    const gl = this.gl, t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(rgba));
    return t;
  }

  _params(mips) {
    const gl = this.gl;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, mips ? gl.LINEAR_MIPMAP_LINEAR : gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  get(pin) {
    let e = this.map.get(pin.id);
    if (!e) {
      e = { pin, tex: null, ready: false, used: 0, promise: null };
      this.map.set(pin.id, e);
      e.promise = pin.anim ? this._loadAnim(e) : this._loadStill(e);
      this._evict();
    }
    e.used = performance.now();
    return e;
  }

  tex(pin) { const e = this.get(pin); return e.ready ? e.tex : this.blank; }

  async ensure(pins, timeout = 2500) {
    const ps = pins.map(p => this.get(p).promise);
    await Promise.race([Promise.allSettled(ps), new Promise(r => setTimeout(r, timeout))]);
  }

  // Stills are decoded off the main thread (createImageBitmap) and uploaded by pump(), at most one per
  // frame: decoding + uploading a dozen pins at once (a drop builds a whole new wall) used to stall the
  // page for 50-75 ms per picture.
  _loadStill(e) {
    return new Promise(res => {
      const done = () => res(e);
      const viaImage = () => {
        const img = new Image();
        img.onload = () => (img.decode ? img.decode() : Promise.resolve()).catch(() => {}).then(() => this._queue(e, img, done));
        img.onerror = done;
        img.src = this.base + e.pin.file;
      };
      if (typeof createImageBitmap !== 'function') return viaImage();
      fetch(this.base + e.pin.file)
        .then(r => r.blob())
        .then(b => createImageBitmap(b, { premultiplyAlpha: 'none' }))
        .then(bmp => this._queue(e, bmp, done))
        .catch(viaImage);
    });
  }

  _queue(e, src, done) {
    (this.uploads || (this.uploads = [])).push({ e, src, done });
    this._fallback();
  }

  // if no frame loop is pumping (boot, or a paused screen), upload from a timer instead
  _fallback() {
    if (this._fb) return;
    this._fb = setTimeout(() => {
      this._fb = null;
      if (!this.uploads || !this.uploads.length) return;
      if (performance.now() - (this.lastPump || 0) > 90) this.pump();
      this._fallback();
    }, 100);
  }

  // call once per frame: upload the oldest decoded picture (more only while the queue is long)
  pump(budgetMs = 4) {
    const q = this.uploads;
    if (!q || !q.length) return;
    const gl = this.gl, t0 = performance.now();
    this.lastPump = t0;
    do {
      const { e, src, done } = q.shift();
      e.tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, e.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
      this._params(true);
      gl.generateMipmap(gl.TEXTURE_2D);
      if (src.close) src.close();
      e.ready = true;
      done();
    } while (q.length > 8 && performance.now() - t0 < budgetMs);
  }

  ready(pins) { return pins.every(p => { const e = this.map.get(p.id); return e && e.ready; }); }

  touch(pins) { const t = performance.now(); for (const p of pins) { const e = this.map.get(p.id); if (e) e.used = t; } }

  async _loadAnim(e) {
    const gl = this.gl;
    try {
      if (typeof ImageDecoder === 'undefined') throw new Error('no ImageDecoder');
      const resp = await fetch(this.base + e.pin.file);
      const dec = new ImageDecoder({ data: resp.body, type: 'image/gif' });
      await dec.tracks.ready;
      const n = dec.tracks.selectedTrack.frameCount;
      e.tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, e.tex);
      this._params(false);
      e.anim = { dec, n, i: 0, next: 0, busy: false };
      await this._frame(e, 0);
      e.ready = true;
    } catch (err) {
      await this._loadStill(e);   // first frame only
    }
    return e;
  }

  async _frame(e, i) {
    const a = e.anim;
    a.busy = true;
    try {
      const r = await a.dec.decode({ frameIndex: i });
      const gl = this.gl;
      gl.bindTexture(gl.TEXTURE_2D, e.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, r.image);
      a.next = performance.now() + Math.max(40, (r.image.duration || 80000) / 1000);
      r.image.close();
    } catch (err) { a.next = performance.now() + 200; }
    a.busy = false;
  }

  // advance animated pins that are on screen
  tick(onScreenIds) {
    const now = performance.now();
    for (const id of onScreenIds) {
      const e = this.map.get(id);
      if (!e || !e.anim || e.anim.busy || now < e.anim.next) continue;
      e.anim.i = (e.anim.i + 1) % e.anim.n;
      this._frame(e, e.anim.i);
    }
  }

  _evict() {
    if (this.map.size <= this.limit) return;
    const arr = [...this.map.values()].filter(e => e.ready).sort((a, b) => a.used - b.used);
    const now = performance.now();
    for (const e of arr) {
      if (this.map.size <= this.limit) break;
      if (now - e.used < 20000) continue;   // never drop something used in the last 20 s
      this.gl.deleteTexture(e.tex);
      if (e.anim) try { e.anim.dec.close(); } catch (_) {}
      this.map.delete(e.pin.id);
    }
  }
}
