"""Connects to the listener and prints a summary of what it sends for N seconds."""
import asyncio, json, sys, time
import websockets
async def main(secs):
    t0 = time.time(); counts = {}; clocks = []; drops = []; first = {}
    async with websockets.connect('ws://127.0.0.1:4360') as ws:
        while time.time() - t0 < secs:
            try: m = json.loads(await asyncio.wait_for(ws.recv(), 1))
            except asyncio.TimeoutError: continue
            counts[m['type']] = counts.get(m['type'], 0) + 1
            first.setdefault(m['type'], m)
            if m['type'] == 'clock': clocks.append((time.time() - t0, m))
            if m['type'] == 'drop': drops.append((round(time.time() - t0, 2), round(m['at']/1000 - t0, 2), m))
    print('counts', counts)
    print('hello', first.get('hello'))
    locked = [c for c in clocks if c[1]['locked']]
    print('first locked clock at', round(locked[0][0], 2) if locked else None, 's; bpm', locked[-1][1]['bpm'] if locked else None)
    nx = [c[1]['next'] for c in locked]
    if len(nx) > 4:
        steps = sorted(set(round(b - a) for a, b in zip(nx, nx[1:]) if b != a))
        print('beat steps between successive clocks (ms):', steps[:12])
        print('lead time (next - now) ms, median:', sorted(round(c[1]['next'] - (t0 + c[0]) * 1000) for c in locked)[len(locked)//2])
    print('drops (received s, heard s, msg):', drops)
    print('levels sample', first.get('levels'))
asyncio.run(main(float(sys.argv[1])))
