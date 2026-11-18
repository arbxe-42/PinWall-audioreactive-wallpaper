"""Real-desktop check: show the desktop (Win+D), capture every screen with the wallpaper and the real
icons, glide the cursor over the collage (hover), toggle Ctrl+Alt+W (ambient) and back, then restore
the windows with Win+D and put the cursor back. Saves test/desk_<step>_<screen>.png."""
import ctypes
import ctypes.wintypes
import os
import time

from PIL import ImageGrab

u = ctypes.windll.user32
u.SetProcessDPIAware()
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test")


def key(*vks):
    for v in vks:
        u.keybd_event(v, 0, 0, 0)
    for v in reversed(vks):
        u.keybd_event(v, 0, 2, 0)


def screens():
    rects = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT), ctypes.c_double)

    def cb(h, dc, r, d):
        rects.append((r.contents.left, r.contents.top, r.contents.right, r.contents.bottom))
        return 1
    u.EnumDisplayMonitors(0, 0, CB(cb), 0)
    return rects


def snap(name):
    full = ImageGrab.grab(all_screens=True)
    vx, vy = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
    out = []
    for (l, t, r, b) in screens():
        tag = "monitor" if (l, t) == (0, 0) else "laptop"
        im = full.crop((l - vx, t - vy, r - vx, b - vy))
        p = os.path.join(OUT, f"desk_{name}_{tag}.png")
        im.save(p)
        out.append(f"{tag} {r - l}x{b - t}")
    return out


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


orig = POINT()
u.GetCursorPos(ctypes.byref(orig))
key(0x5B, 0x44)            # Win+D: show desktop
time.sleep(4)
try:
    print("a", snap("a"))
    # glide across the middle of the monitor with REAL input events (SetCursorPos alone is invisible
    # to the input hooks Lively uses to forward the mouse to wallpapers)
    pw, ph = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
    for i in range(40):
        x, y = 1050 + i * 10, 760
        u.mouse_event(0x8001, int(x * 65535 / (pw - 1)), int(y * 65535 / (ph - 1)), 0, 0)  # MOVE | ABSOLUTE
        time.sleep(0.03)
    time.sleep(1.2)
    print("hover", snap("hover"))
    key(0x11, 0x12, 0x57)      # Ctrl+Alt+W -> ambient
    time.sleep(3)
    print("ambient", snap("ambient"))
    key(0x11, 0x12, 0x57)      # back to reactive
    time.sleep(1)
finally:
    u.SetCursorPos(orig.x, orig.y)
    key(0x5B, 0x44)            # Win+D again: windows come back, whatever happened
    print("restored")
