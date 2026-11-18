"""Record a clean demo clip of Pin Wall on the main monitor, with the sound the PC plays.

  listener/.venv/Scripts/python.exe tools/record_demo.py --seconds 25 [--out demo/raw] [--no-wait]

What it does:
  1. puts the wall in Reactive mode (through the listener), shows the desktop (Win+D) and hides the desktop
     icons, so the clip shows only the wall
  2. waits for music to start (up to 3 min; start the song after launching this), then records the monitor
     (GPU capture, no mouse pointer) and the PC's sound (loopback) for --seconds
  3. puts everything back: icons, windows, mode
  4. writes <out>/video.mp4, <out>/audio.wav, <out>/meta.json; tools/make_demo.py turns them into the clip

Nothing is uploaded; the files stay on this machine.
"""
import argparse
import asyncio
import ctypes
import json
import os
import subprocess
import sys
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "listener", "state.json")
u = ctypes.windll.user32


def key(*vks):
    for v in vks:
        u.keybd_event(v, 0, 0, 0)
    for v in reversed(vks):
        u.keybd_event(v, 0, 2, 0)


def desktop_listview():
    """The desktop icon list (SysListView32 under Progman or a WorkerW) and its SHELLDLL_DefView parent."""
    found = []

    def cb(h, _):
        dv = u.FindWindowExW(h, 0, "SHELLDLL_DefView", None)
        if dv:
            found.append((dv, u.FindWindowExW(dv, 0, "SysListView32", None)))
        return True
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    u.EnumWindows(proto(cb), 0)
    return found[0] if found else (None, None)


def set_icons(visible):
    dv, lv = desktop_listview()
    if not dv:
        return None
    was = bool(u.IsWindowVisible(lv))
    if was != visible:
        u.SendMessageW(dv, 0x0111, 0x7402, 0)   # WM_COMMAND "show desktop icons" toggle
        time.sleep(0.4)
    return was


def set_mode(mode):
    async def go():
        import websockets
        async with websockets.connect("ws://127.0.0.1:4360") as ws:
            await ws.recv()
            await ws.send(json.dumps({"type": "mode", "mode": mode}))
            await asyncio.sleep(0.3)
    try:
        asyncio.run(go())
        return True
    except Exception as ex:
        print("could not reach the listener:", ex)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=25)
    ap.add_argument("--out", default=os.path.join(ROOT, "demo", "raw"))
    ap.add_argument("--no-wait", action="store_true", help="start at once instead of waiting for music")
    ap.add_argument("--wait-max", type=float, default=180)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    import soundcard as sc

    try:
        old_mode = json.load(open(STATE, encoding="utf-8")).get("mode", "reactive")
    except Exception:
        old_mode = "reactive"
    spk = sc.default_speaker()
    mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
    sr, block = 48000, 480
    icons_were = None
    try:
        set_mode("reactive")
        key(0x5B, 0x44)                      # Win+D: show the desktop
        time.sleep(1.0)
        icons_were = set_icons(False)
        time.sleep(1.0)
        with mic.recorder(samplerate=sr, channels=2, blocksize=block) as rec:
            if not a.no_wait:
                print(f"waiting for music on {spk.name} (start the song now) ...", flush=True)
                t_end = time.time() + a.wait_max
                while time.time() < t_end:
                    x = rec.record(numframes=block * 5)
                    if 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9) > -45:
                        break
                else:
                    print("no music heard; giving up")
                    return 1
            # start the screen capture, then record the sound in this thread
            vid = os.path.join(a.out, "video.mp4")
            cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                   "-i", "ddagrab=output_idx=0:framerate=30:draw_mouse=0",
                   "-t", f"{a.seconds + 1.5:.2f}", "-vf", "hwdownload,format=bgra,format=yuv420p",
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", vid]
            t_launch = time.time()
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
            chunks = []
            t_audio0 = time.time()
            n = int((a.seconds + 1.5) * sr / block)
            for _ in range(n):
                chunks.append(rec.record(numframes=block))
            p.wait(timeout=60)
        audio = np.concatenate(chunks).astype(np.float32)
        import soundfile as sf
        sf.write(os.path.join(a.out, "audio.wav"), audio, sr)
        json.dump({"t_launch": t_launch, "t_audio0": t_audio0, "seconds": a.seconds, "device": spk.name,
                   "recorded": time.strftime("%Y-%m-%d %H:%M:%S")}, open(os.path.join(a.out, "meta.json"), "w"), indent=1)
        print(f"recorded {len(audio) / sr:.1f} s of sound and the screen -> {a.out}")
        return 0
    finally:
        if icons_were is not None:
            set_icons(icons_were)
        time.sleep(0.3)
        key(0x5B, 0x44)                      # Win+D again: the windows come back
        if old_mode != "reactive":
            set_mode(old_mode)


if __name__ == "__main__":
    sys.exit(main())
