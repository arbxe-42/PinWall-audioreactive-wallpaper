"""Screenshot a local page with headless Edge.

Usage: python tools/shot.py <file-or-url> <out.png> [width height] [extra query] [budget_ms]
Waits until the PNG exists (headless Edge returns before it finishes writing).
"""
import os
import subprocess
import sys
import time

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def shot(target, out, w=1920, h=1080, query="", budget=8000):
    if os.path.exists(target):
        url = "file:///" + os.path.abspath(target).replace(os.sep, "/").replace(" ", "%20")
    else:
        url = target
    if query:
        url += ("&" if "?" in url else "?") + query
    out = os.path.abspath(out)
    if os.path.exists(out):
        os.remove(out)
    prof = os.path.join(os.environ.get("TEMP", "."), "pinwall-shot-%d" % (abs(hash(out)) % 10000))
    subprocess.run([EDGE, "--headless=new", "--hide-scrollbars", "--allow-file-access-from-files",
                    "--enable-webgl", "--ignore-gpu-blocklist", "--use-angle=d3d11",
                    f"--user-data-dir={prof}", f"--window-size={w},{h}", f"--virtual-time-budget={budget}",
                    f"--screenshot={out}", url], capture_output=True)
    for _ in range(120):
        if os.path.exists(out) and os.path.getsize(out) > 0:
            break
        time.sleep(0.5)
    time.sleep(0.8)
    return out if os.path.exists(out) else None


if __name__ == "__main__":
    a = sys.argv[1:]
    w, h = (int(a[2]), int(a[3])) if len(a) >= 4 else (1920, 1080)
    q = a[4] if len(a) >= 5 else ""
    b = int(a[5]) if len(a) >= 6 else 8000
    print(shot(a[0], a[1], w, h, q, b))
