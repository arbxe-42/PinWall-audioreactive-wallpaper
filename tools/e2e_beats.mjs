// End-to-end beat test: runs the wallpaper's own beat code (wallpaper/src/audio.js) in Node against a
// listener on a test port, and records the wall-clock time of every beat it fires.
// Usage: node tools/e2e_beats.mjs <port> <out.json> <seconds>
const [port, out, secs] = process.argv.slice(2);
globalThis.location = { search: '?ws=' + port };
const { Music, LEAD } = await import('../wallpaper/src/audio.js');
const fs = await import('node:fs');

const m = new Music();
const fired = [];
const hits = [];
const clocks = [];
m.on('beat', b => fired.push({ t: Date.now() + LEAD, pos: b.pos, down: b.down, bpm: b.bpm }));
m.on('hit', h => hits.push({ t: Date.now() + LEAD, slot: h.slot, beat: h.beat, s: h.strength, so: h.strengthOld, w: h.settle }));
const origClock = m._clock.bind(m);
m._clock = msg => { clocks.push({ t: Date.now(), next: msg.next, period: msg.period, locked: msg.locked }); origClock(msg); };

let last = performance.now();
const iv = setInterval(() => {               // the wallpaper calls update() once per frame (60 fps)
  const n = performance.now();
  m.update((n - last) / 1000);
  last = n;
}, 16);
setTimeout(() => {
  clearInterval(iv);
  fs.writeFileSync(out, JSON.stringify({ fired, hits, clocks }));
  process.exit(0);
}, Number(secs) * 1000);
