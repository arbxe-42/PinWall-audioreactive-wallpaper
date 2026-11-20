"""Pin Wall listener: hears what the PC plays, finds the beat, tells the wallpaper.

  * captures the default output device with WASAPI loopback (soundcard), 48 kHz
  * runs listener/detect.py on it (the same code the bench scores)
  * maps "sound time" to the wall clock and adds the output device's delay
    (devices.json: Bluetooth speakers are typically heard ~150-300 ms after Windows sends audio)
  * broadcasts over ws://127.0.0.1:4360 to the wallpaper:
      hello  {mode, device, delay}
      clock  {next (epoch ms the next beat is HEARD), period (ms), locked, conf, bpm, pos, accent[4], down}
      levels {b, m, h}            ~60 per second, delayed to match what you hear
      tape   {t, dt, lag, a, k}   ~30 per second in reactive mode: per-frame loudness + KickNet confidence
      drop   {at (epoch ms heard), jump}
      mode   {mode: "reactive" | "ambient"}
      silence {}
  * Ctrl+Alt+W toggles reactive / ambient; tray icon too; mode saved in state.json
  * audio is analysed in memory only, never written anywhere

Run:      listener/.venv/Scripts/pythonw.exe listener/server.py          (no window)
Replay:   listener/.venv/Scripts/python.exe listener/server.py --replay song.wav --start 60
          (feeds a file at real-time pace, silently, as if it were playing: for testing)
"""
import argparse
import asyncio
import ctypes
import ctypes.wintypes
import json
import os
import queue
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from detect import Detector, FPS  # noqa: E402

PORT = 4360
SR = 48000
BLOCK = 480  # 10 ms
STATE = os.path.join(HERE, "state.json")
DEVICES = os.path.join(HERE, "devices.json")
LOG = os.path.join(HERE, "listener.log")
QUIT_FLAG = os.path.join(HERE, "quit.flag")   # written on tray Quit; keeper.py then stops too


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if sys.stdout:
        try:
            print(line, flush=True)
        except Exception:
            pass


# ---------------------------------------------------------------- state
class State:
    def __init__(self):
        # every fresh start (sign-in, or the keeper restarting the listener) comes up Reactive: an Ambient
        # choice lasts until then. It used to be remembered forever, which left the wall ignoring the music
        # after a restart without the user noticing why.
        self.mode = "reactive"
        try:
            json.dump({"mode": self.mode}, open(STATE, "w", encoding="utf-8"))
        except OSError:
            pass
        self.device = "?"
        self.delay = 0.0
        self.out = queue.Queue()  # messages to broadcast
        self.lock = threading.Lock()

    def set_mode(self, mode):
        self.mode = mode
        try:
            json.dump({"mode": mode}, open(STATE, "w", encoding="utf-8"))
        except OSError:
            pass
        self.send({"type": "mode", "mode": mode})
        log("mode ->", mode)

    def toggle(self):
        self.set_mode("ambient" if self.mode == "reactive" else "reactive")

    def send(self, msg):
        self.out.put(msg)


def device_delay(name):
    try:
        cfg = json.load(open(DEVICES, encoding="utf-8"))["devices"]
    except Exception:
        cfg = [{"match": "Bluetooth", "delay": 0.2}]
    for d in cfg:
        if d["match"].lower() in name.lower():
            return float(d["delay"])
    return 0.0


def save_device_delay(name, delay):
    """Store a calibrated delay for this exact output device (first in the list, so it wins)."""
    try:
        cfg = json.load(open(DEVICES, encoding="utf-8"))
    except Exception:
        cfg = {"devices": []}
    devs = [d for d in cfg.get("devices", []) if d.get("match") != name]
    devs.insert(0, {"match": name, "delay": round(delay, 3), "calibrated": time.strftime("%Y-%m-%d %H:%M")})
    cfg["devices"] = devs
    json.dump(cfg, open(DEVICES, "w", encoding="utf-8"), indent=1)
    log("calibrated", name, "->", round(delay * 1000), "ms")


# ---------------------------------------------------------------- analysis loop
class Analyzer:
    """Feeds audio to the detector and turns its state into wall-clock messages."""

    BASE_OUT = 0.015  # typical Windows output buffering on wired/laptop speakers

    def __init__(self, st: State, sr=SR):
        self.st = st
        self.sr = sr
        self.reset()

    def reset(self):
        self.det = Detector(self.sr)
        self.samples = 0
        self.offset = None  # wall_time(sample s) = offset + s / sr
        self.last_clock = None
        self.last_clock_sent = 0.0
        self.level_q = []
        self.tape, self.tape_sent = [], 0.0

    def feed(self, block, wall_end):
        """block: mono float32 just captured; wall_end: wall time its last sample was captured."""
        n = len(block)
        self.samples += n
        est = wall_end - self.samples / self.sr
        self.offset = est if self.offset is None else self.offset + 0.02 * (est - self.offset)
        heard = self.BASE_OUT + self.st.delay
        events = self.det.process(block)
        d = self.det
        for e in events:
            if e["type"] == "drop" and self.st.mode == "reactive":
                at = self.offset + e["t"] + heard
                self.st.send({"type": "drop", "at": round(at * 1000), "jump": e.get("jump_db")})
                log("drop", e)
            elif e["type"] == "silence":
                self.st.send({"type": "silence"})
            elif e["type"] == "kick_fast" and self.st.mode == "reactive":
                # a kick was heard in the audio Windows is sending out: tell the wallpaper when YOU will hear it
                at = self.offset + e["t"] + heard
                self.st.send({"type": "hit", "at": round(at * 1000, 1), "z": e.get("z", 0), "z0": e.get("z0", e.get("z", 0))})
            elif e["type"] in ("lock", "loose", "flip"):
                log(e["type"], "bpm", None if d.P is None else round(60 * FPS / d.P, 1))
        # clock: the next predicted beat, in heard wall time
        if d.next_beat is not None and d.P:
            nxt = self.offset + d.t(d.next_beat) + heard
            per = d.P / FPS
            key = (d.beat_index, d.locked, round(per, 4), d.active)
            now = time.time()
            if key != self.last_clock or now - self.last_clock_sent > 0.5:
                self.last_clock, self.last_clock_sent = key, now
                down = int(np.argmax(d.p_kick[0::2] + 0.5 * d.p_acc))
                self.st.send({"type": "clock", "next": round(nxt * 1000, 1), "period": round(per * 1000, 2),
                              "locked": bool(d.locked), "conf": round(d.conf, 2), "bpm": round(60 / per, 2),
                              "pos": int(d.beat_index % 4), "accent": [round(float(a), 2) for a in d.p_acc],
                              "down": down, "active": bool(d.active),
                              "pk": [round(float(a), 2) for a in d.p_kick]})
        # kick tape for the clock (reactive mode only): every 10 ms frame's loudness and KickNet confidence,
        # stamped in heard wall time like the hits, ~30 batches per second. KickNet answers for the sound
        # `lag` frames back, so the wallpaper draws k[i] at t + (i - lag) * dt.
        tr, d.trace = d.trace, []
        if self.st.mode != "reactive":
            self.tape = []
        elif tr:
            self.tape += tr
            now = time.time()
            if now - self.tape_sent >= 0.033:
                self.tape_sent = now
                at = self.offset + (self.tape[0][0] + 1) * d.hop / self.sr + heard
                self.st.send({"type": "tape", "t": round(at * 1000, 1), "dt": round(1000 * d.hop / self.sr, 3),
                              "lag": d.nn.net.lag if d.nn is not None else 0,
                              "a": [round(f[1], 2) for f in self.tape], "k": [round(float(f[2]), 2) for f in self.tape]})
                self.tape = []
        # levels, delayed so they match what you hear
        self.level_q.append((wall_end + heard, d.levels))
        now = time.time()
        while self.level_q and self.level_q[0][0] <= now:
            _, lv = self.level_q.pop(0)
            self._lv = lv
        if getattr(self, "_lv", None) is not None and now - getattr(self, "_lv_sent", 0) >= 1 / 60:
            self._lv_sent = now
            b, m, h = self._lv
            self.st.send({"type": "levels", "b": round(b, 3), "m": round(m, 3), "h": round(h, 3)})


def capture_loop(st: State, stop: threading.Event):
    import soundcard as sc
    an = Analyzer(st)
    while not stop.is_set():
        try:
            spk = sc.default_speaker()
            st.device = spk.name
            st.delay = device_delay(spk.name)
            st.send({"type": "hello", "mode": st.mode, "device": st.device, "delay": st.delay})
            log("capturing", spk.name, "delay", st.delay)
            mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            an.reset()
            last_check = time.time()
            with mic.recorder(samplerate=SR, channels=2, blocksize=BLOCK) as rec:
                while not stop.is_set():
                    data = rec.record(numframes=BLOCK)
                    wall = time.time()
                    an.feed(data.mean(axis=1).astype(np.float32), wall)
                    if wall - last_check > 2.0:  # output device switched?
                        last_check = wall
                        if sc.default_speaker().name != spk.name:
                            log("output device changed")
                            break
        except Exception as ex:  # device vanished etc: retry
            log("capture error:", repr(ex))
            time.sleep(1.0)


def replay_loop(st: State, stop: threading.Event, path, start, delay, switch_at=None, delay2=None, info=None,
                duration=None):
    """Feed a file at real-time pace, silently, as if it were playing. For tests: switch_at/delay2
    imitate changing output devices mid-song (new delay, analyser restarted, exactly like
    capture_loop does), and info gets the wall-clock start so a harness can line things up."""
    import soundfile as sf
    x, sr = sf.read(path, start=int(start * sf.info(path).samplerate), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if duration:
        x = x[:int(duration * sr)]
    st.device, st.delay = f"replay:{os.path.basename(path)}", delay
    st.send({"type": "hello", "mode": st.mode, "device": st.device, "delay": st.delay})
    an = Analyzer(st, sr)
    blk = int(sr / 100)
    time.sleep(1.5)                      # give a test client time to connect
    t0 = time.time()
    if info:
        json.dump({"t0": t0, "start": start, "sr": sr, "base_out": Analyzer.BASE_OUT, "delay": delay,
                   "switch_at": switch_at, "delay2": delay2}, open(info, "w"))
    i = 0
    switched = False
    log("replaying", path, "from", start, "s (silent)")
    while not stop.is_set() and i + blk <= len(x):
        target = t0 + (i + blk) / sr
        dt = target - time.time()
        if dt > 0:
            time.sleep(dt)
        if switch_at is not None and not switched and i / sr >= switch_at:
            switched = True
            st.delay = delay2
            st.device += " (switched)"
            st.send({"type": "hello", "mode": st.mode, "device": st.device, "delay": st.delay})
            an.reset()
            log("replay: output switched, delay", delay2)
        an.feed(x[i:i + blk], time.time())
        i += blk
    log("replay finished")
    stop.set()


# ---------------------------------------------------------------- websocket
async def ws_main(st: State, stop: threading.Event):
    import websockets
    clients = set()

    async def handler(ws):
        clients.add(ws)
        try:
            await ws.send(json.dumps({"type": "hello", "mode": st.mode, "device": st.device, "delay": st.delay}))
            async for msg in ws:  # the wallpaper may ask to toggle (e.g. from a click)
                try:
                    m = json.loads(msg)
                    if m.get("type") == "toggle":
                        st.toggle()
                    elif m.get("type") == "mode":
                        if m["mode"] != st.mode:
                            st.set_mode(m["mode"])
                    elif m.get("type") == "calib":
                        save_device_delay(st.device, float(m["delay"]))
                        st.delay = float(m["delay"])
                        st.send({"type": "hello", "mode": st.mode, "device": st.device, "delay": st.delay})
                    elif m.get("type") == "test_drop":   # bench/tools: trigger a shatter on every wallpaper (perf probe)
                        st.send({"type": "drop", "at": round(time.time() * 1000 + 300), "jump": 0, "test": True, "fxonly": bool(m.get("fxonly"))})
                        log("test drop")
                    elif m.get("type") == "stat":
                        log("wallpaper", {k: v for k, v in m.items() if k != "type"})
                except Exception:
                    pass
        finally:
            clients.discard(ws)

    async with websockets.serve(handler, "127.0.0.1", PORT):
        log(f"ws://127.0.0.1:{PORT} ready")
        while not stop.is_set():
            batch = []
            try:
                while True:
                    batch.append(st.out.get_nowait())
            except queue.Empty:
                pass
            if batch and clients:
                # keep only the newest levels message per tick
                lv = [m for m in batch if m["type"] == "levels"]
                rest = [m for m in batch if m["type"] != "levels"] + lv[-1:]
                payloads = [json.dumps(m) for m in rest]
                for ws in list(clients):
                    for p in payloads:
                        try:
                            await ws.send(p)
                        except Exception:
                            clients.discard(ws)
                            break
            await asyncio.sleep(0.008)


# ---------------------------------------------------------------- images
def pick_folder():
    """Windows folder picker (via PowerShell, so no extra Python packages are needed)."""
    import subprocess
    ps = ("Add-Type -AssemblyName System.Windows.Forms; $d = New-Object System.Windows.Forms.FolderBrowserDialog; "
          "$d.Description = 'Pick the folder with your images for Pin Wall'; $d.ShowNewFolderButton = $false; "
          "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }")
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True,
                       creationflags=0x08000000)
    return r.stdout.strip() or None


def import_images(st, folder=None):
    """Re-import the wallpaper's images from a folder, then tell the wallpaper to reload."""
    import subprocess
    folder = folder or pick_folder()
    if not folder:
        return
    log("importing images from", folder)
    py = sys.executable.replace("pythonw.exe", "python.exe")
    r = subprocess.run([py, os.path.join(os.path.dirname(HERE), "tools", "prep_pins.py"), "--src", folder],
                       capture_output=True, text=True, creationflags=0x08000000)
    log((r.stdout.strip().splitlines() or ["import failed"])[-1], r.stderr.strip()[-300:])
    st.send({"type": "reload"})


# ---------------------------------------------------------------- hotkey + tray
def hotkey_loop(st: State, stop: threading.Event):
    user32 = ctypes.windll.user32
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
    if not user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, 0x57):  # W
        log("hotkey Ctrl+Alt+W is taken by another program")
        return
    log("hotkey Ctrl+Alt+W registered")
    msg = ctypes.wintypes.MSG()
    while not stop.is_set():
        if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == 0x0312:  # WM_HOTKEY
                st.toggle()
        else:
            time.sleep(0.03)
    user32.UnregisterHotKey(None, 1)


def tray_icon_image(mode):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = (182, 255, 46, 255) if mode == "reactive" else (123, 44, 255, 255)
    pts = []
    import math
    for k in range(16):
        r = 30 if k % 2 == 0 else 13
        a = k * math.pi / 8 - math.pi / 2
        pts.append((32 + r * math.cos(a), 32 + r * math.sin(a)))
    d.polygon(pts, fill=col)
    return im


def run_tray(st: State, stop: threading.Event):
    import pystray
    icon = None

    def label(_):
        return f"Mode: {st.mode} (Ctrl+Alt+W)"

    def refresh():
        icon.icon = tray_icon_image(st.mode)
        icon.title = f"Pin Wall Â· {st.mode} Â· {st.device}"
        icon.update_menu()

    def toggle(_icon=None, _item=None):
        st.toggle()
        refresh()

    def quit_(_icon, _item):
        # tell the keeper this was the user's choice, so it doesn't start the listener again
        try:
            open(QUIT_FLAG, "w").close()
        except OSError:
            pass
        log("quit from the tray")
        stop.set()
        icon.stop()

    def change_images(_icon=None, _item=None):
        threading.Thread(target=import_images, args=(st,), daemon=True).start()

    def calibrate(_icon=None, _item=None):
        os.startfile(os.path.join(HERE, "calibrate.html"))

    def open_folder(_icon=None, _item=None):
        os.startfile(os.path.join(os.path.dirname(HERE), "wallpaper", "pins"))

    menu = pystray.Menu(
        pystray.MenuItem("Toggle reactive / ambient", toggle, default=True),
        pystray.MenuItem("Change images...", change_images),
        pystray.MenuItem("Calibrate speaker delay...", calibrate),
        pystray.MenuItem(label, None, enabled=False),
        pystray.MenuItem(lambda _: f"Output: {st.device} (+{int(st.delay * 1000)} ms)", None, enabled=False),
        pystray.MenuItem("Quit Pin Wall listener", quit_),
    )
    icon = pystray.Icon("pinwall", tray_icon_image(st.mode), "Pin Wall", menu)

    def watcher():
        last = None
        while not stop.is_set():
            if st.mode != last:
                last = st.mode
                try:
                    refresh()
                except Exception:
                    pass
            time.sleep(0.3)

    threading.Thread(target=watcher, daemon=True).start()
    icon.run()


# ---------------------------------------------------------------- main
def main():
    global PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", help="feed this audio file at real-time pace instead of capturing (silent)")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--delay", type=float, default=0.0, help="replay: pretend output delay (s)")
    ap.add_argument("--switch-at", type=float, default=None, help="replay: seconds in, pretend the output device changed")
    ap.add_argument("--delay2", type=float, default=0.0, help="replay: output delay after the switch")
    ap.add_argument("--info", default=None, help="replay: write start time info here (json)")
    ap.add_argument("--duration", type=float, default=None, help="replay: seconds to play")
    ap.add_argument("--no-tray", action="store_true")
    ap.add_argument("--port", type=int, default=PORT, help="websocket port (tests use another one)")
    a = ap.parse_args()
    PORT = a.port

    # one instance only (exit code 3 tells keeper.py a listener is already running)
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "PinWallListener")
    if ctypes.windll.kernel32.GetLastError() == 183 and not a.replay:
        log("already running")
        sys.exit(3)
    # any uncaught error, in any thread, goes to the log (the listener once died silently)
    import traceback

    def _one_line(et, ev, tb):
        return " | ".join("".join(traceback.format_exception(et, ev, tb)).strip().splitlines())

    sys.excepthook = lambda et, ev, tb: log("FATAL", _one_line(et, ev, tb))
    threading.excepthook = lambda h: log("thread error in", h.thread.name if h.thread else "?",
                                         _one_line(h.exc_type, h.exc_value, h.exc_traceback))
    st = State()
    stop = threading.Event()
    if a.replay:
        threading.Thread(target=replay_loop, args=(st, stop, a.replay, a.start, a.delay, a.switch_at, a.delay2, a.info, a.duration), daemon=True).start()
    else:
        threading.Thread(target=capture_loop, args=(st, stop), daemon=True).start()
    threading.Thread(target=lambda: asyncio.run(ws_main(st, stop)), daemon=True).start()
    if not a.replay:
        threading.Thread(target=hotkey_loop, args=(st, stop), daemon=True).start()
    if a.no_tray or a.replay:
        try:
            while not stop.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            stop.set()
    else:
        # the tray runs on the main thread; if it ever fails (it can after power or display changes), keep
        # listening without it instead of letting the whole listener exit
        try:
            run_tray(st, stop)
        except Exception as ex:
            log("tray failed, listening on without it:", repr(ex))
            while not stop.is_set():
                time.sleep(0.5)
    stop.set()
    log("listener stopped")
    del mutex


if __name__ == "__main__":
    main()
