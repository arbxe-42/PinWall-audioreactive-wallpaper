"""Trigger a test shatter on every running Pin Wall and print the perf report each wallpaper logs.

  listener/.venv/Scripts/python.exe tools/drop_test.py [--port 4360] [--n 1]

The wallpaper records frame gaps, CPU time per frame and long tasks for 2.5 s after the drop and sends them
as a 'perf' stat; the listener writes it to listener.log. No sound involved.
"""
import argparse
import asyncio
import json
import os
import time

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "listener", "listener.log")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4360)
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--fxonly", action="store_true", help="shatter the current wall without loading a new one")
    a = ap.parse_args()
    import websockets
    for i in range(a.n):
        size = os.path.getsize(LOG)
        async with websockets.connect(f"ws://127.0.0.1:{a.port}") as ws:
            await ws.recv()   # hello
            await ws.send(json.dumps({"type": "test_drop", "fxonly": a.fxonly}))
            await asyncio.sleep(4.5)
        with open(LOG, encoding="utf-8") as f:
            f.seek(size)
            for line in f:
                if "'perf'" in line:
                    print(line.strip())
        time.sleep(1)


asyncio.run(main())
