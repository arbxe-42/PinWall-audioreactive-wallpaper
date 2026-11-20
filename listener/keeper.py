"""Keeps the Pin Wall listener running.

The Startup shortcut launches this (pythonw keeper.py) instead of server.py. It starts the listener and,
whenever the listener exits for any reason other than the user picking Quit in the tray, starts it again
after a few seconds. Why: the listener once died silently overnight (around a power-source change) and,
since the laptop only sleeps and wakes, nothing started it again until the next sign-in, so the wallpaper
stopped reacting to music.

  * one keeper at a time (a named mutex); a second copy exits at once
  * Quit in the tray writes listener/quit.flag; the keeper sees it and exits too
  * crash loops back off: more than 5 restarts in 2 minutes -> wait a minute before the next try
  * everything is logged to listener/listener.log with a "keeper" prefix
"""
import ctypes
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")
QUIT_FLAG = os.path.join(HERE, "quit.flag")
LOG = os.path.join(HERE, "listener.log")


def log(*a):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + "keeper " + " ".join(str(x) for x in a) + "\n")
    except OSError:
        pass


def main():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "PinWallKeeper")
    if ctypes.windll.kernel32.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
        return
    # run the listener with the same (windowless) python as this keeper
    py = sys.executable
    if os.path.basename(py).lower() == "python.exe" and os.path.exists(os.path.join(os.path.dirname(py), "pythonw.exe")):
        py = os.path.join(os.path.dirname(py), "pythonw.exe")
    try:
        os.remove(QUIT_FLAG)
    except OSError:
        pass
    log("started; keeping the listener running")
    starts = []
    while True:
        starts = [t for t in starts if time.time() - t < 120] + [time.time()]
        p = subprocess.Popen([py, SERVER], cwd=HERE)
        code = p.wait()
        if os.path.exists(QUIT_FLAG):
            log("listener quit from the tray; keeper stopping")
            try:
                os.remove(QUIT_FLAG)
            except OSError:
                pass
            break
        if code == 3:              # another listener is already running (started by hand): check again later
            starts.pop()
            time.sleep(20)
            continue
        wait = 60 if len(starts) > 5 else 3
        log(f"listener exited (code {code}); restarting in {wait} s")
        time.sleep(wait)
    del mutex


if __name__ == "__main__":
    main()
